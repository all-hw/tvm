This folder is an example of TVM integration with All-HW CI services.

All-HW is a system for remote usage of microcontroller boards. This includes both remote debugging in IDE and running CI tasks. A CI task is defined by a firmware image and an input data file. The image is flashed onto the board and then input data are sent to the board's UART. The data put out from the UART are saved and delivered to the CI task creator.

The example is based on an earlier-existing example of running a number of ML models on a board connected to the local host. The demo script uses Project API (implemented in grovety/template_project/microtvm_api_server.py) to generate a C++ project implementing a model for the given microcontroller to build it, to flash it, and to run it with the given input data. This is run.py located in this directory. It must be run in the VirtualBox virtual machine, which is started by "vagrant ssh" run from the tvm/apps/microtvm/reference-vm/zephyr folder.

To demonstrate TVM/All-HW CI integration, microtvm_api_server.py has been modified to use alternative implementation of some Project API methods. The implementation is isolated in the file grovety/template_project/ci_api_server.py. The implementation supports a number of ProjectOptions specific for All-HW CI infrastructure:

 

ci_url - Base URL for the (HTTP requests to) CI server

ci_api_key - The key giving access to CI server services for the given type of microcontrollers

ci_timeout - Timeout (in seconds) for the CI task execution (to run the firmware on a board)

ci_rate - Baud rate for the UART used as CI task input/output; depends on example project code regarding UART IO

ci_log - CI task logging level; "0" means no logging; "DEBUG" means extensive logging

 

However, the default CI options necessary to run the example successfully are hardcoded, except the timeout; but it is set correctly in the updated run.py (which, in particular, is an example of usage for these parameters).

The demo script must be called from the TVM root folder like this:

python apps/microtvm/grovety/run.py --platform=f746_disco --model=<model>

where <model> can take values "cifar10", "mnist8", and "synth".

This script does the following:

- generates a C++ project implementing a model for the f746_disco development board

- builds the project to make a firmware image

- passes the image along with the test input data to the All-HW CI server to create a CI task (this is incapsulated in the write_transport Project API method)

- repeatedly requests the task status to get output data (this is incapsulated in the read_transport Project API method)

- parses the output data and prints it to the stdout

- the three items above are repeated for every test input data available for the given model
