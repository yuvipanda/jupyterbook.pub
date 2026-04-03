import { useEffect, useState } from "react";
import copy from "copy-to-clipboard";
import { Answer, resolve } from "./resolver";
import { useDebounce } from "use-debounce";

function makeShareableLink(baseUrl: string, repoUrl: string) {
    return new URL(`${baseUrl}${encodeURIComponent(repoUrl)}/`, window.location.origin);
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

export function LinkGenerator({ baseUrl }: { baseUrl: string }) {
    const [repoUrl, setRepoUrl] = useState<string>("");
    const [shareUrl, setShareUrl] = useState<URL | null>(null);
    const [resolvedRepo, setResolvedRepo] = useState<Answer | null>(null);
    const [debouncedRepoUrl] = useDebounce(repoUrl, 1000);

    useEffect(() => {
        const validateUrl = async () => {
            if (debouncedRepoUrl === "") {
                setResolvedRepo(null);
                return;
            }

            const answer = await resolve(debouncedRepoUrl);
            if (answer === null) {
                setResolvedRepo(null);
            } else {
                setResolvedRepo(answer);
            }
        };
        validateUrl();
    }, [debouncedRepoUrl]);

    return (
        <div className="row bg-body-tertiary mt-4">
            <form className="p-4">
                <div className="m-3 col-12">
                    <div className="input-group">
                        <div className="form-floating">
                            <input
                                type="input"
                                className="form-control"
                                id="repo-url"
                                placeholder="Enter your repository URL here"
                                onChange={(e) => {
                                    const rawRepoUrl = e.target.value;
                                    const normalizedRepoUrl =
                                        normalizeRepoUrl(rawRepoUrl);
                                    setRepoUrl(normalizedRepoUrl);

                                    setShareUrl(
                                        normalizeRepoUrl === null
                                            ? null
                                            : makeShareableLink(
                                                  baseUrl,
                                                  normalizedRepoUrl,
                                              ),
                                    );
                                }}
                            ></input>
                            <label htmlFor="repoUrl">
                                {resolvedRepo === null ||
                                resolvedRepo.certainity === "DoesNotExist" ? (
                                    <span>Enter your repository URL here</span>
                                ) : (
                                    <>
                                        <span className="badge text-bg-secondary">
                                            {resolvedRepo.kind}
                                        </span>
                                        {Object.entries(resolvedRepo.data).map(
                                            ([key, value]) => (
                                                <span className="mx-1" key={key}>
                                                    <code title={key}>{value}</code>
                                                </span>
                                            ),
                                        )}
                                    </>
                                )}
                            </label>
                        </div>
                        <button
                            className="btn btn-primary"
                            type="button"
                            onClick={() =>
                                (window.location.href = shareUrl?.toString() ?? "")
                            }
                            disabled={
                                resolvedRepo === null ||
                                resolvedRepo.certainity === "DoesNotExist"
                            }
                        >
                            Go!
                        </button>
                    </div>
                    <small>
                        Supports GitHub (Repos,{" "}
                        <abbr title="Branches, Commits & Tags">Refs</abbr>, Action
                        Artifacts & PRs), Public Google Drive Folders,{" "}
                        <abbr title="From Zenodo, Figshare & Dataverse">DOIs</abbr>,{" "}
                        <a href="https://github.com/yuvipanda/repoproviders?tab=readme-ov-file#supported-repositories">
                            and many others
                        </a>
                    </small>
                </div>
                <div className="m-3 input-group">
                    <div className="form-floating">
                        <input
                            type="input"
                            className="form-control"
                            id="share-url"
                            placeholder="Shareable link to your rendered book"
                            readOnly
                            value={shareUrl?.toString() ?? ""}
                        ></input>
                        <label className="form-label">
                            Share this link with anyone so they can see a rendered
                            version of your JupyterBook
                        </label>
                    </div>
                    <button
                        className="btn btn-outline-secondary"
                        type="button"
                        onClick={() => copy(shareUrl?.toString() ?? "")}
                        disabled={shareUrl === null}
                    >
                        <i className="bi bi-copy"></i>
                    </button>
                </div>
            </form>
        </div>
    );
}
