import { notFound } from "next/navigation";
import { RESEARCH_CONDITION_KEYS, type ResearchConditionKey } from "@/lib/research-data";
import ConditionDetailClient from "./ConditionDetailClient";

export function generateStaticParams() {
  return RESEARCH_CONDITION_KEYS.map((key) => ({ key }));
}

export const dynamicParams = false;

export default function ConditionDetailPage({ params }: { params: { key: string } }) {
  if (!RESEARCH_CONDITION_KEYS.includes(params.key as ResearchConditionKey)) {
    notFound();
  }
  return <ConditionDetailClient conditionKey={params.key as ResearchConditionKey} />;
}
