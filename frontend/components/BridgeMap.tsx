"use client";
import { useEffect, useState } from "react";
import { BRIDGES } from "@/lib/data";

type MapModule = {
  MapContainer: any;
  TileLayer: any;
  CircleMarker: any;
  Popup: any;
};

export default function BridgeMap() {
  const [mod, setMod] = useState<MapModule | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (typeof document !== "undefined") {
      const id = "leaflet-css";
      if (!document.getElementById(id)) {
        const link = document.createElement("link");
        link.id = id;
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        link.crossOrigin = "";
        document.head.appendChild(link);
      }
    }

    Promise.all([import("react-leaflet"), import("leaflet")]).then(
      ([rl, leafletModule]) => {
        if (cancelled) return;
        const IconCtor = (leafletModule as any).Icon?.Default
          ? (leafletModule as any).Icon
          : (leafletModule as any).default?.Icon;
        if (IconCtor?.Default?.prototype) {
          delete IconCtor.Default.prototype._getIconUrl;
          IconCtor.Default.mergeOptions({
            iconRetinaUrl:
              "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
            iconUrl:
              "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
            shadowUrl:
              "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
          });
        }
        setMod({
          MapContainer: rl.MapContainer,
          TileLayer: rl.TileLayer,
          CircleMarker: rl.CircleMarker,
          Popup: rl.Popup,
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  if (!mod) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl bg-gray-100">
        <span className="text-sm text-gray-400">Loading map...</span>
      </div>
    );
  }

  const { MapContainer, TileLayer, CircleMarker, Popup } = mod;

  const coords: Record<string, [number, number]> = {
    "bridge-indus-hwy-01": [25.402444, 68.311417],
    "bridge-kotri-01": [25.442389, 68.315556],
    "bridge-sukkur-01": [27.679694, 68.845639],
    "bridge-guddu-01": [28.419333, 69.712583],
  };

  const color: Record<string, string> = {
    CRITICAL: "#ef4444",
    WARNING: "#f97316",
    WATCH: "#eab308",
    SAFE: "#22c55e",
  };

  const popupNames: Record<string, string> = {
    "bridge-indus-hwy-01": "Indus Highway Bridge (HYD-KHI)",
    "bridge-kotri-01": "Kotri Barrage Bridge",
    "bridge-sukkur-01": "Sukkur Barrage Bridge",
    "bridge-guddu-01": "Guddu Barrage Bridge",
  };

  return (
    <div
      style={{
        height: "360px",
        borderRadius: "16px",
        overflow: "hidden",
        border: "1px solid #e5e7eb",
      }}
    >
      <MapContainer
        center={[26.8, 68.6]}
        zoom={7}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom={false}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap"
        />
        {BRIDGES.map((b) => {
          const pos = coords[b.id];
          if (!pos) return null;
          return (
            <CircleMarker
              key={b.id}
              center={pos}
              radius={14}
              fillColor={color[b.severity] ?? "#6b7280"}
              color="white"
              weight={2}
              fillOpacity={0.9}
            >
              <Popup>
                <strong>{popupNames[b.id]}</strong>
                <br />
                {b.location}
                <br />
                Risk: {b.risk_score}/100 — {b.severity}
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
