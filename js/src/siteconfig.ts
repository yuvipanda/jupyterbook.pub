export interface SiteConfig {
    site_title: string
    site_heading: string
    site_subheading: string
}


export async function getSiteConfig() : Promise<SiteConfig> {
    // FIXME: BaseURL support plz
    const queryUrl = new URL("api/v1/site-config", window.location.origin);

    const resp = await fetch(queryUrl);

    return (await resp.json()) as SiteConfig;
}
