Builders
======

.. automodule:: jupyterbook_pub.builder

   :members:


   .. code-block:: python

      from jupyterbook_pub.app import JupyterBookPubApp
      from jupyterbook_pub.executor import LocalProcessExecutor
      from jupyterbook_pub.builder.lite import JupyterLiteBuilder
      from traitlets.config import Config

      config = Config(
        LocalProcessExecutor = Config(
            builder_class = JupyterLiteBuilder
        )
      )

      app = JupyterBookPubApp(config=config)
      app.initialize()
      app.start()
      

.. autoclass:: jupyterbook_pub.builder.lite.JupyterLiteBuilder
.. autoconfigurable:: jupyterbook_pub.builder.book.JupyterBook2Builder
