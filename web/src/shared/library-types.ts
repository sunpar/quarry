export interface LibraryStatus {
  id: "highcharts" | "scichart";
  enabled: boolean;
  reason: string | null;
  license: string | null;
  entry: string | null;
}

/** An enabled licensed library as the runtime loads it; the host sends these with each mount. */
export interface LicensedLibrary {
  id: LibraryStatus["id"];
  entry: string;
  license: string | null;
}
