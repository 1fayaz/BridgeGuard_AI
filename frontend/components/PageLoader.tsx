"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";

export default function PageLoader() {
  const pathname = usePathname();
  const [loading, setLoading] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setLoading(true);
    setVisible(true);

    const hideTimer = setTimeout(() => {
      setLoading(false);
    }, 800);

    const removeTimer = setTimeout(() => {
      setVisible(false);
    }, 1100);

    return () => {
      clearTimeout(hideTimer);
      clearTimeout(removeTimer);
    };
  }, [pathname]);

  if (!visible) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "#0a2e25",
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        opacity: loading ? 1 : 0,
        transition: "opacity 0.3s ease",
      }}
    >
      <div
        style={{
          animation: "logoPulse 1s ease-in-out infinite",
          marginBottom: "32px",
        }}
      >
        <Image
          src="/logo.png"
          alt="BridgeGuard AI"
          width={160}
          height={160}
          priority
        />
      </div>

      <div
        style={{
          color: "white",
          fontSize: "24px",
          fontWeight: "700",
          fontFamily: "system-ui, sans-serif",
          letterSpacing: "0.5px",
          marginBottom: "8px",
          animation: "fadeInUp 0.5s ease forwards",
        }}
      >
        BridgeGuard <span style={{ color: "#4ade80" }}>AI</span>
      </div>

      <div
        style={{
          color: "#94a3b8",
          fontSize: "13px",
          fontFamily: "system-ui, sans-serif",
          letterSpacing: "2px",
          textTransform: "uppercase",
          marginBottom: "40px",
          animation: "fadeInUp 0.5s ease 0.1s both",
        }}
      >
        Smarter Bridges · Safer Tomorrow
      </div>

      <div
        style={{
          width: "200px",
          height: "3px",
          backgroundColor: "rgba(255,255,255,0.1)",
          borderRadius: "2px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            backgroundColor: "#0F6E56",
            borderRadius: "2px",
            animation: "progressBar 0.8s ease forwards",
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: "2px",
          background:
            "linear-gradient(90deg, transparent, #0F6E56, transparent)",
          animation: "scanLine 1s ease-in-out infinite",
        }}
      />

      <style>{`
        @keyframes logoPulse {
          0%, 100% {
            transform: scale(1);
            filter: drop-shadow(0 0 8px rgba(15, 110, 86, 0.4));
          }
          50% {
            transform: scale(1.05);
            filter: drop-shadow(0 0 20px rgba(15, 110, 86, 0.8));
          }
        }

        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes progressBar {
          from { width: 0%; }
          to { width: 100%; }
        }

        @keyframes scanLine {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100vw); }
        }
      `}</style>
    </div>
  );
}
