import { apiFetch } from "./client";
import type {
  CatalogBrandsResponse,
  CatalogCounts,
  CatalogParams,
  CatalogPerfumesResponse,
} from "./types";

export function fetchCatalogPerfumes(
  params?: CatalogParams,
): Promise<CatalogPerfumesResponse> {
  return apiFetch<CatalogPerfumesResponse>(
    "/api/v1/catalog/perfumes",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export function fetchCatalogBrands(
  params?: CatalogParams,
): Promise<CatalogBrandsResponse> {
  return apiFetch<CatalogBrandsResponse>(
    "/api/v1/catalog/brands",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export function fetchCatalogCounts(): Promise<CatalogCounts> {
  return apiFetch<CatalogCounts>("/api/v1/catalog/counts");
}
