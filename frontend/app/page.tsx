"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, CheckCircle, Clock, MapPin, WifiOff } from "lucide-react";
import { getBridges } from "@/lib/api";

interface Bridge {
  bridge_id: string;
  name: string;
  location: string | null;
  current_risk: {
    assessment_id: number;
    risk_score: number | null;
    severity: string | null;
    explanation: string;
    review_status: string;
    assessed_at: string;
  } | null;
}

export default function BridgeListPage() {
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchBridges() {
      try {
        const data = await getBridges();
        setBridges(data);
      } catch (err) {
        setError("Failed to load bridges");
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    fetchBridges();
  }, []);

  const getSeverityBadge = (severity: string | null) => {
    if (!severity) return (
      <Badge variant="secondary" className="gap-1">
        <Clock className="h-3 w-3" /> Unassessed
      </Badge>
    );
    switch (severity) {
      case "CRITICAL":
        return (
          <Badge variant="destructive" className="gap-1">
            <AlertCircle className="h-3 w-3" /> CRITICAL
          </Badge>
        );
      case "HIGH":
        return (
          <Badge variant="destructive" className="gap-1">
            <AlertCircle className="h-3 w-3" /> HIGH
          </Badge>
        );
      case "MEDIUM":
        return (
          <Badge variant="secondary" className="gap-1 bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200">
            <AlertCircle className="h-3 w-3" /> MEDIUM
          </Badge>
        );
      case "LOW":
        return (
          <Badge variant="default" className="gap-1">
            <CheckCircle className="h-3 w-3" /> LOW
          </Badge>
        );
      default:
        return (
          <Badge variant="secondary" className="gap-1">
            {severity}
          </Badge>
        );
    }
  };

  const getScoreColor = (score: number | null) => {
    if (score === null) return "text-muted-foreground";
    if (score >= 80) return "text-red-600 dark:text-red-400";
    if (score >= 60) return "text-amber-600 dark:text-amber-400";
    if (score >= 30) return "text-blue-600 dark:text-blue-400";
    return "text-green-600 dark:text-green-400";
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading bridges…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <WifiOff className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
          <h2 className="text-xl font-semibold mb-2">Unable to load bridges</h2>
          <p className="text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Bridge Overview</h1>
        <p className="text-muted-foreground mt-1">
          {bridges.length} bridge{bridges.length !== 1 ? "s" : ""} in current municipality
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {bridges.map((bridge) => (
          <Card key={bridge.bridge_id} className="transition-shadow hover:shadow-lg">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <CardTitle className="text-lg truncate">{bridge.name}</CardTitle>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground mt-1">
                    <MapPin className="h-3.5 w-3.5 flex-shrink-0" />
                    <span className="truncate">
                      {bridge.location || "Location unknown"}
                    </span>
                  </div>
                </div>
                {getSeverityBadge(bridge.current_risk?.severity ?? null)}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">
                    Risk Score
                  </p>
                  <p className={`text-3xl font-bold ${getScoreColor(bridge.current_risk?.risk_score ?? null)}`}>
                    {bridge.current_risk?.risk_score ?? "—"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">
                    Status
                  </p>
                  <p className="text-lg font-medium capitalize">
                    {bridge.current_risk?.review_status?.toLowerCase() ?? "unassessed"}
                  </p>
                </div>
              </div>

              {bridge.current_risk && (
                <div className="pt-2 border-t">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
                    Assessment
                  </p>
                  <p className="text-sm line-clamp-2">
                    {bridge.current_risk.explanation}
                  </p>
                  <p className="text-xs text-muted-foreground mt-2">
                    Assessed: {new Date(bridge.current_risk.assessed_at).toLocaleDateString()}
                  </p>
                </div>
              )}

              {!bridge.current_risk && (
                <div className="pt-2 border-t text-center text-sm text-muted-foreground">
                  No risk assessment available for this bridge.
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {bridges.length === 0 && (
        <div className="text-center py-12">
          <MapPin className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
          <h2 className="text-xl font-semibold mb-2">No bridges found</h2>
          <p className="text-muted-foreground">
            No bridges have been registered for this municipality.
          </p>
        </div>
      )}
    </div>
  );
}

interface LayoutProps {
  children: React.ReactNode;
}