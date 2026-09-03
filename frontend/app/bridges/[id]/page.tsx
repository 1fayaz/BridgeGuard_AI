import { notFound } from "next/navigation";
import { BRIDGES } from "@/lib/data";
import BridgeDetailClient from "./BridgeDetailClient";

export function generateStaticParams() {
  return BRIDGES.map((bridge) => ({ id: bridge.id }));
}

export const dynamicParams = false;

export default function BridgeDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const bridge = BRIDGES.find((b) => b.id === params.id);

  if (!bridge) {
    notFound();
  }

  return <BridgeDetailClient bridge={bridge} />;
}
