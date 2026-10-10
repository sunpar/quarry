export interface LibraryStatus {
  id: "highcharts" | "scichart";
  enabled: boolean;
  reason: string | null;
  license: string | null;
  entry: string | null;
}
