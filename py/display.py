import ast
import argparse

def display_ast(file_path):
    with open(file_path, "r") as source_file:
        source_code = source_file.read()
    
    parsed_ast = ast.parse(source_code, filename=file_path)
    print(ast.dump(parsed_ast, indent=4))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Display the AST of a Python source file.")
    parser.add_argument("file", help="Path to the Python source file")
    args = parser.parse_args()
    
    display_ast(args.file)
