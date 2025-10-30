import builtins

def override_input():
    original_input = builtins.input

    def custom_input(prompt=""):
        print(f"__NEED_INPUT__{prompt}", end="", flush=True)
        return original_input()

    builtins.input = custom_input

grading_inputs = []
grading_index = 0

def set_grading_inputs(lines):
    global grading_inputs, grading_index
    grading_inputs = lines
    grading_index = 0

def override_input(grading_mode=False):
    original_input = builtins.input

    def custom_input(prompt=""):
        if grading_mode:
            global grading_index
            if grading_index < len(grading_inputs):
                val = grading_inputs[grading_index]
                grading_index += 1
                return val
            raise EOFError("No more grading input")
        else:
            print(f"__NEED_INPUT__{prompt}", end="", flush=True)
            return original_input()

    builtins.input = custom_input