import { useState } from "react";
import copy from "copy-to-clipboard";


function makeShareableLink(repoUrl: string) {
    // FIXME: I am committing a cardinal sin here that makes it difficult to host this under subpaths
    // but how do I get this information in here otherwise? I do not know. Forgive me for my sins
    const baseUrl = window.location.origin;
    return (new URL("repo/" + encodeURIComponent(repoUrl) + "/", baseUrl)).toString();
}

export function LinkGenerator() {
    const [repoUrl, setRepoUrl] = useState("");
    const [shareUrl, setShareUrl] = useState("");
    return (
        <div className="row bg-body-tertiary mt-4">
            <form className="p-4">
                <div className="m-3 input-group">
                    <div className="form-floating">
                        <input type="input" className="form-control" id="repo-url" placeholder="Enter your repository URL here" value={repoUrl} onChange={e => {
                            setRepoUrl(e.target.value);
                            if (e.target.value.trim() === "") {
                                setShareUrl("");
                            } else {
                                setShareUrl(makeShareableLink(e.target.value));
                            }
                        }}></input>
                        <label htmlFor="repoUrl">Enter your repository URL here</label>
                    </div>
                    <button className="btn btn-primary" type="button" onClick={() => window.location.href = shareUrl}>Go!</button>
                </div>
                <div className="m-3 input-group">
                    <div className="form-floating">
                        <input type="input" className="form-control" id="share-url" placeholder="Shareable link to your rendered book" readOnly value={shareUrl}></input>
                        <label className="form-label">Share this link with anyone so they can see a rendered version of your JupyterBook</label>
                    </div>
                    <button className="btn btn-outline-secondary" type="button" onClick={() => copy(shareUrl)} disabled={shareUrl === ""}><i className="bi bi-copy"></i></button>
                </div>
            </form>
        </div>
    )
}