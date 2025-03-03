Quickstart
==========

Installation
------------
Create a virtual environment and install Flowno:

.. code-block:: bash

   python -m venv .venv  # requires Python 3.10+
   source .venv/bin/activate
   pip install flowno

Quickstart Example
------------------
Below is a minimal example to illustrate how to define and run a trivial flow:

.. testcode::

   from flowno import node, FlowHDL

   @node
   async def Add(x, y):  # pay careful attention to the 'async'
       return x + y

   with FlowHDL() as f:
       # create an Add node instance with two constant inputs
       f.sum_node = Add(1, 2)  

   f.run_until_complete()
   print(f.sum_node.get_data())

Expected output:

.. testoutput::

   (3,)

