import os
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import dataclasses
import shutil
from repoproviders import resolve, fetch
from repoproviders.resolvers.base import DoesNotExist, Exists, MaybeExists, Repo
import mimetypes
import asyncio
from tornado.web import RequestHandler, StaticFileHandler, url
import tornado
import tempfile
from urllib.parse import quote
import hashlib

def hash_repo(repo: Repo) -> str:
    return hashlib.sha256(f"{repo.__class__.__name__}:{dataclasses.asdict(repo)}".encode()).hexdigest()

async def render_if_needed(repo: Repo, base_url: str):
    repo_hash = hash_repo(repo)
    repo_path = Path("repos") / repo_hash
    built_path = Path("built") / repo_hash
    env = os.environ.copy()
    env["BASE_URL"] = base_url
    if not built_path.exists():
        if not repo_path.exists():
            yield f"Fetching {repo}...\n"
            await fetch(repo, repo_path)
            yield f"Fetched {repo}"

        command = [
            "jupyter", "book", "build", "--html"
        ]
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=repo_path, env=env
        )

        stdout, stderr = [s.decode() for s in await proc.communicate()]
        retcode = await proc.wait()

        yield stdout
        yield stderr

        shutil.copytree(repo_path / "_build/html", built_path)

templates_loader = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"))

class HomeHandler(RequestHandler):
    def get(self):
        self.write(templates_loader.get_template("home.html").render())

class RepoHandler(RequestHandler):

    def get_spec_from_request(self, prefix):
        """
        Re-extract spec from request.path.
        Get the original, raw spec, without tornado's unquoting.
        This is needed because tornado converts 'foo%2Fbar/ref' to 'foo/bar/ref'.
        """
        idx = self.request.path.index(prefix)
        spec = self.request.path[idx + len(prefix) :]
        return spec

    async def get(self, repo_spec: str, path: str):
        spec = self.get_spec_from_request("/repo/")

        raw_repo_spec, _ = spec.split("/", 1)
        answers = await resolve(repo_spec, True)
        last_answer = answers[-1]
        print(1)
        match last_answer:
            case Exists(repo):
                print(2)
                repo_hash = hash_repo(repo)
                built_path = Path("built") / repo_hash
                if not built_path.exists():
                    base_url = f"/repo/{raw_repo_spec}"
                    async for line in render_if_needed(repo, base_url):
                        self.write(line)
                # This is a *sure* path traversal attack
                full_path = built_path / path
                if full_path.is_dir():
                    full_path = full_path / "index.html"
                mimetype, encoding = mimetypes.guess_type(full_path)
                if encoding == "gzip":
                    mimetype = "application/gzip"
                if mimetype:
                    self.set_header("Content-Type", mimetype)
                with open(full_path, 'rb') as f:
                    # This is super inefficient
                    print(f"serving {full_path}")
                    self.write(f.read())
            case MaybeExists(repo):
                print(f"maybe exists {repo}")
            case DoesNotExist(repo):
                raise tornado.web.HTTPError(404, f"{repo} could not be resolved")


async def main():
    app = tornado.web.Application([
        ("/", HomeHandler),
        url(r"/repo/(.*?)/(.*)", RepoHandler, name="repo"),
        ("/static/(.*)", StaticFileHandler, {"path": str(Path(__file__).parent / "static")})
    ], debug=True)
    app.listen(9200)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())