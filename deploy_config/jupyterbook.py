from jupyterbook_pub.builder.book import JupyterBook2Builder
from jupyterbook_pub.executor import LocalProcessExecutor

c.BuildExecutor.builder_class = JupyterBook2Builder
c.JupyterBookPubApp.executor_class = LocalProcessExecutor

c.JupyterBookPubApp.site_title = "JupyterBook.pub"
c.JupyterBookPubApp.site_heading = "JupyterBook.pub"
c.JupyterBookPubApp.site_subheading = (
    "Instantly build and share your JupyterBook repository wherever it is"
)
