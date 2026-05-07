Executors
======

.. automodule:: jupyterbook_pub.executor

   :members:


   .. code-block:: python

      from jupyterbook_pub.app import JupyterBookPubApp
      from jupyterbook_pub.executor import DockerExecutor
      from traitlets.config import Config

      config = Config(
        JupyterBookPubApp = Config(
            executor_class=DockerExecutor,
        ),
        DockerExecutor = Config(
            image = "quay.io/foo/bar:latest",
            builder_config_file = "./config.json"
        )
      )

      app = JupyterBookPubApp(config=config)
      app.initialize()
      app.start()
      

.. autoconfigurable:: DockerExecutor
.. autoconfigurable:: LocalProcessExecutor
.. autoconfigurable:: KubernetesExecutor
