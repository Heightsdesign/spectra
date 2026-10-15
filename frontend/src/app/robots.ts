import type { MetadataRoute } from "next";

// This is a pre-launch preview. Revisit together with metadata before release.
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", disallow: "/" } };
}
