import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // 相对路径：便携包/自定义协议下都能从任意根目录加载资源
  base: "./",
  server: { port: 5183, strictPort: true },
  build: { target: "es2022" },
});
