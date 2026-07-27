import type { Metadata } from "next";
import "./globals.css";
import { Shell } from "../components/Shell";

export const metadata: Metadata = { title: "Council · 审议台", description: "用独立分析、对抗审查与证据核验，得到更可靠的答案。" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><Shell>{children}</Shell></body></html>;
}
