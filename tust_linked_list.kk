struct Node:
    next: Node
    data: str

struct LinkedList:
    head: Node
    count: i32

func print_linked_list(linked_list: LinkedList) -> void:
    current_node = linked_list.head
    i: i32 = 0
    while i < linked_list.count:
        printf("%s ", current_node.data)
        current_node = current_node.next
        i = i + 1

node3: Node
node3.data = "!"

node2: Node
node2.data = "you"
node2.next = node3

node1: Node
node1.data = "love"
node1.next = node2

node0: Node
node0.data = "I"
node0.next = node1

linked_list: LinkedList
linked_list.head = node0
linked_list.count = 4

print_linked_list(linked_list)
