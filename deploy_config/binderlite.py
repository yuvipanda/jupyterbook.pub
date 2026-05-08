from jupyterbook_pub.builder.lite import JupyterLiteBuilder
from jupyterbook_pub.executor import LocalProcessExecutor

c.BuildExecutor.builder_class = JupyterLiteBuilder
c.JupyterBookPubApp.executor_class = LocalProcessExecutor

c.JupyterBookPubApp.site_title = "BinderLite (name tbd)"
c.JupyterBookPubApp.site_heading = "BinderLite (name tbd)"
c.JupyterBookPubApp.site_subheading = "Instantly build and share interactive computational notebook repositories with JupyterLite"
