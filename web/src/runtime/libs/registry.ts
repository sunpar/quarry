import type { LicensedLibrary } from "@/shared/library-types";

let registered: LicensedLibrary[] = [];

/** The host passes the enabled licensed libraries with every mount. */
export function setLicensed(list: LicensedLibrary[]): void {
  registered = list;
}

export function licensed(id: LicensedLibrary["id"]): LicensedLibrary | null {
  return registered.find((l) => l.id === id) ?? null;
}

export function notEnabled(id: LicensedLibrary["id"]): Error {
  return new Error(
    `${id} is not enabled on this server; set libraries.${id}_license and libraries.${id}_path in config.toml`,
  );
}
