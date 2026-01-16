export interface Answer {
    certainity: "Exists" | "MaybeExists" | "DoesNotExist"
    kind: string
    data: object
}

export async function resolve(question: string) : Promise<Answer | null> {
    // FIXME: BaseURL support plz
    const queryUrl = new URL("api/v1/resolve", window.location.origin);
    queryUrl.searchParams.append("q", question);

    const resp = await fetch(queryUrl);
    if (!resp.ok) {
        return null;
    }

    return (await resp.json()) as Answer;
}