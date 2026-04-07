export interface Answer {
    certainity: "Exists" | "MaybeExists" | "DoesNotExist";
    kind: string;
    data: object;
}

export async function resolve(
    baseUrl: string,
    question: string,
): Promise<Answer | null> {
    // FIXME: BaseURL support plz
    const queryUrl = new URL(`${baseUrl}api/v1/resolve`, window.location.href);
    queryUrl.searchParams.append("q", question);

    const cookie = document.cookie;

    const xsrfTokenMatch = cookie.match('\\b_xsrf=([^;]*)\\b');
    if (xsrfTokenMatch) {
      queryUrl.searchParams.append('_xsrf', xsrfTokenMatch[1]);
    }

    const resp = await fetch(queryUrl);
    if (!resp.ok) {
        return null;
    }

    return (await resp.json()) as Answer;
}
