import { Alert, Button } from "antd";

interface Props {
  title?: string;
  message: string;
  onRetry?: () => void;
  style?: React.CSSProperties;
}

/**
 * UI-09：接口失败时的页面态。
 *
 * 以前只有一条会自动消失的 toast，页面停在骨架屏/全 0 上，看起来像「还在加载」。
 * 这里给一个持久的错误 + 重试入口。
 */
export function LoadError({ title = "加载失败", message, onRetry, style }: Props) {
  return (
    <Alert
      type="error"
      showIcon
      style={style}
      message={title}
      description={message}
      action={onRetry ? <Button size="small" onClick={onRetry}>重试</Button> : undefined}
    />
  );
}
