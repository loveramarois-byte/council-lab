import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Council · 四席审议工作台",
    short_name: "Council",
    description: "让四个独立模型席位依次回应、互相评议，并由总结席给出最终答案。",
    start_url: "/",
    display: "standalone",
    background_color: "#f8f7f4",
    theme_color: "#cc6848",
    orientation: "portrait-primary",
    icons: [
      { src: "/icons/council-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/council-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/council-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
