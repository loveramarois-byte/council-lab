import type { Metadata } from "next";
import "./globals.css";
import { Shell } from "../components/Shell";
import { PwaRegistrar } from "../components/PwaRegistrar";

export const metadata: Metadata = {
  title: "Council · 审议台",
  description: "让四个独立模型席位依次回应、互相评议，并由总结席给出最终答案。",
  applicationName: "Council",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "Council" },
  icons: { apple: "/icons/council-192.png" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><PwaRegistrar /><Shell>{children}</Shell></body></html>;
}
