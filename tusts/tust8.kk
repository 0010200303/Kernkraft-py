import LinkedList

node3: LinkedList.Node
node3.data = "!"

node2: LinkedList.Node
node2.data = "you"
node2.next = node3

node1: LinkedList.Node
node1.data = "love"
node1.next = node2

node0: LinkedList.Node
node0.data = "I"
node0.next = node1

linked_list: LinkedList.LinkedList
linked_list.head = node0
linked_list.count = 4

LinkedList.print(linked_list)
