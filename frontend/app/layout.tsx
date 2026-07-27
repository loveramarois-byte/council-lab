import type { Metadata } from "next";
import "./globals.css";
import { Shell } from "../components/Shell";

export const metadata: Metadata = { title: "Council · 审议台", description: "让四个模型席位公开回应，并把你的资料与补充带进最终答案。" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><Shell>{children}</Shell></body></html>;
}
