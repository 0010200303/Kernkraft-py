struct Node:
    next: Node
    data: str

struct LinkedList:
    head: Node
    count: i32

func print_node_data(node: Node) -> void:
    printf("%s ", node.data)

func print(linked_list: LinkedList) -> void:
    current_node = linked_list.head
    i: i32 = 0
    while i < linked_list.count:
        print_node_data(current_node)
        current_node = current_node.next
        i = i + 1
