"use client";

import { CircleAlert, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

export default function PairPage() {
  const [error, setError] = useState("");

  useEffect(() => {
    const pairingPayload = decodeURIComponent(window.location.hash.slice(1));
    const desktopPairing = pairingPayload.startsWith("desktop:");
    const token = pairingPayload.replace(/^(desktop|mobile):/, "");
    window.history.replaceState(null, "", "/pair");
    if (!token) {
      setError("配对码无效，请回到电脑重新扫描。");
      return;
    }

    const pair = async () => {
      const response = await fetch("/mobile-access/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, device: desktopPairing ? "desktop" : "mobile" }),
      });
      if (!response.ok) throw new Error("配对码已失效，请回到电脑重新扫描。");
      window.location.replace("/");
    };
    void pair().catch((reason) => setError(reason instanceof Error ? reason.message : "手机配对失败"));
  }, []);

  return <div className="pair-page">
    <div className="pair-progress">
      {error ? <CircleAlert size={22} /> : <LoaderCircle className="spin" size={22} />}
      <p className="eyebrow terracotta">COUNCIL MOBILE</p>
      <h1>{error ? "无法完成配对" : "正在接入圆桌"}</h1>
      <p>{error || "正在验证这台手机…"}</p>
    </div>
  </div>;
}
