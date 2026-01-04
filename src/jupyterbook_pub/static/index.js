function onRepoChange() {
    const repoUrl = document.getElementById('repoUrl').value;
    const shareUrl = window.location.href + "repo/" + encodeURIComponent(repoUrl) + "/";
    document.getElementById('shareUrl').value = shareUrl;
    console.log(repoUrl);
}

function go() {
    const repoUrl = document.getElementById('repoUrl').value;
    const shareUrl = window.location.href + "repo/" + encodeURIComponent(repoUrl) + "/";
    window.location.href = shareUrl;
}

document.getElementById('repoUrl').addEventListener('keyup', onRepoChange);
document.getElementById('go').addEventListener('click', go);