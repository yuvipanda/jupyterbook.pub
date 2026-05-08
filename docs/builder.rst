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
      
.. autoconfigurable:: jupyterbook_pub.builder.Builder
.. autoconfigurable:: jupyterbook_pub.builder.GenericBuilder
.. autoconfigurable:: jupyterbook_pub.builders.lite.JupyterLiteBuilder
.. autoconfigurable:: jupyterbook_pub.builders.book.JupyterBook2Builder
