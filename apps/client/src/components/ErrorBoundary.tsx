import { Alert, Button, Space } from "antd";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { openLogFolder } from "../simlink";

interface Props {
  children: ReactNode;
  /** 路由变化时传进来的 key：换页后自动清掉上一次的错误，不用整窗重启。 */
  resetKey?: string;
}

interface State {
  error: Error | null;
  info: string;
}

/**
 * UI-15：页面渲染抛错时不要整窗白屏。
 *
 * Tauri 里白屏只能重启客户端；这里给「重新加载本页 / 打开日志目录」，并把堆栈写进
 * aoc-core 日志（控制台），方便排查字段缺失导致的 `.toFixed()` 之类崩溃。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info: info.componentStack || "" });
    // 控制台 + core 日志（Tauri 的 webview 控制台不易打开，先保证有一份可复制的文本）
    console.error("[AOC] 页面渲染失败", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null, info: "" });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <Alert
          type="error"
          showIcon
          message="页面渲染出错（界面已拦截，不会白屏）"
          description={(
            <div>
              <p style={{ margin: "0 0 6px" }}>{this.state.error.message}</p>
              <pre style={{ margin: 0, maxHeight: 200, overflow: "auto", fontSize: 11 }}>
                {this.state.error.stack || this.state.info}
              </pre>
            </div>
          )}
          action={(
            <Space direction="vertical">
              <Button size="small" type="primary" onClick={() => this.setState({ error: null, info: "" })}>
                重试
              </Button>
              <Button size="small" onClick={() => void openLogFolder()}>打开日志</Button>
            </Space>
          )}
        />
      </div>
    );
  }
}
