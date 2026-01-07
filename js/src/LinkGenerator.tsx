import { useEffect, useState } from "react";
import copy from "copy-to-clipboard";
import { Answer, resolve } from "./resolver";
import { useDebounce } from 'use-debounce';

function makeShareableLink(repoUrl: string) {
    // FIXME: I am committing a cardinal sin here that makes it difficult to host this under subpaths
    // but how do I get this information in here otherwise? I do not know. Forgive me for my sins
    const baseUrl = window.location.origin;
    return new URL("repo/" + encodeURIComponent(repoUrl) + "/", baseUrl);
}

function normalizeRepoUrl(repoUrl: string) {
    // If it's a valid URL, just return it
    try {
        const parsedUrl = new URL(repoUrl);
        return repoUrl;
    } catch (error) {
        if (error instanceof TypeError) {
            // Invalid URL!
            if (!repoUrl.startsWith("https://")) {
                return "https://" + repoUrl;
            } else {
                return "";
            }
        }
        throw error;
    }
}

export function LinkGenerator() {
    const [repoUrl, setRepoUrl] = useState<string>("");
    const [shareUrl, setShareUrl] = useState<URL | null>(null);
    const [resolvedRepo, setResolvedRepo] = useState<Answer | null>(null);
    const [debouncedRepoUrl] = useDebounce(repoUrl, 1000);

    useEffect(() => {
        const validateUrl = async () => {
            if (debouncedRepoUrl === "") {
                setResolvedRepo(null);
                return
            }

            const answer = await resolve(debouncedRepoUrl);
            if (answer === null) {
                setResolvedRepo(null);
            } else {
                setResolvedRepo(answer)
            }
        };
        validateUrl();
    }, [debouncedRepoUrl]);

    return (
        <div className="row bg-body-tertiary mt-4">
            <form className="p-4">
                <div className="m-3 input-group">
                    <div className="form-floating">
                        <input type="input" className="form-control" id="repo-url" placeholder="Enter your repository URL here" onChange={e => {
                            const rawRepoUrl = e.target.value;
                            const normalizedRepoUrl = normalizeRepoUrl(rawRepoUrl);
                            setRepoUrl(normalizedRepoUrl);
                            if (normalizedRepoUrl === null) {
                                setShareUrl(null);
                            } else {
                                setShareUrl(makeShareableLink(normalizedRepoUrl));
                            }
                        }}></input>
                        <label htmlFor="repoUrl">
                            {(resolvedRepo === null || resolvedRepo.certainity !== "Exists") ? <span>Enter your repository URL here</span> : <>

                                <span className="badge text-bg-secondary">{resolvedRepo.kind}</span>
                                {Object.entries(resolvedRepo.data).map(([key, value]) =>
                                    <span className="mx-1" key={key}>
                                        <code title={key}>{value}</code></span>
                                )}
                            </>
                            }
                        </label>
                    </div>
                    <button className="btn btn-primary" type="button" onClick={() => window.location.href = shareUrl.toString()} disabled={resolvedRepo === null || resolvedRepo.certainity !== "Exists"}>Go!</button>
                </div>
                <div className="m-3 input-group">
                    <div className="form-floating">
                        <input type="input" className="form-control" id="share-url" placeholder="Shareable link to your rendered book" readOnly value={shareUrl ? shareUrl.toString() : ""}></input>
                        <label className="form-label">Share this link with anyone so they can see a rendered version of your JupyterBook</label>
                    </div>
                    <button className="btn btn-outline-secondary" type="button" onClick={() => copy(shareUrl?.toString())} disabled={shareUrl === null}><i className="bi bi-copy"></i></button>
                </div>
            </form>
        </div>
    )
}