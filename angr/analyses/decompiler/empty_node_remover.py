# pylint:disable=unused-argument
import claripy
import ailment

from .sequence_walker import SequenceWalker
from .region_identifier import MultiNode
from .structurer_nodes import SequenceNode, CodeNode, ConditionNode, SwitchCaseNode, ConditionalBreakNode, \
    BreakNode, LoopNode, CascadingConditionNode
from .condition_processor import ConditionProcessor


class EmptyNodeRemover:
    """
    Rewrites a node and its children to remove empty nodes.

    The following optimizations are performed at the same time:
    - Convert if (A) { } else { ... } to if(!A) { ... } else { }
    """
    def __init__(self, node):
        self.root = node

        self.removed_sequences = [ ]
        self.replaced_sequences = { }

        handlers = {
            SequenceNode: self._handle_Sequence,
            CodeNode: self._handle_Code,
            ConditionNode: self._handle_Condition,
            CascadingConditionNode: self._handle_CascadingCondition,
            SwitchCaseNode: self._handle_SwitchCase,
            LoopNode: self._handle_Loop,

            MultiNode: self._handle_MultiNode,
            BreakNode: self._handle_Default,
            ConditionalBreakNode: self._handle_Default,

            ailment.Block: self._handle_Block,
        }
        self._walker = SequenceWalker(handlers=handlers)
        r = self._walker.walk(self.root)
        if r is None:
            self.result = SequenceNode(nodes=[])
        else:
            # Make sure it's still a sequence node
            if not isinstance(r, SequenceNode):
                r = SequenceNode(nodes=[r])
            self.result = r

    #
    # Handlers
    #

    def _handle_Sequence(self, node, **kwargs):

        new_nodes = [ ]
        for node_ in node.nodes:
            new_node = self._walker._handle(node_)
            if new_node is not None:
                if isinstance(new_node, SequenceNode):
                    new_nodes.extend(new_node.nodes)
                else:
                    new_nodes.append(new_node)

        if not new_nodes:
            self.removed_sequences.append(node)
            return None
        if len(new_nodes) == 1:
            # Remove the unnecessary sequence node
            self.replaced_sequences[node] = new_nodes[0]
            return new_nodes[0]

        sn = SequenceNode(nodes=new_nodes)
        self.replaced_sequences[node] = sn
        return sn

    def _handle_MultiNode(self, node: MultiNode, **kwargs):

        new_nodes = [ ]
        for node_ in node.nodes:
            new_node = self._walker._handle(node_)
            if new_node is not None:
                if isinstance(new_node, MultiNode):
                    new_nodes.extend(new_node.nodes)
                else:
                    new_nodes.append(new_node)

        if not new_nodes:
            return None
        if len(new_nodes) == 1:
            # Remove the unnecessary MultiNode
            return new_nodes[0]
        return MultiNode(new_nodes)

    def _handle_Code(self, node, **kwargs):
        inner_node = self._walker._handle(node.node)
        if inner_node is None:
            return None
        if claripy.is_true(node.reaching_condition):
            # Remove the unnecessary CodeNode
            return inner_node
        return CodeNode(inner_node, node.reaching_condition)

    def _handle_Condition(self, node, **kwargs):

        true_node = self._walker._handle(node.true_node)
        false_node = self._walker._handle(node.false_node)

        if true_node is None and false_node is None:
            # empty node
            return None
        if true_node is None and false_node is not None:
            # swap them
            return ConditionNode(node.addr,
                                 node.reaching_condition,
                                 ConditionProcessor.simplify_condition(claripy.Not(node.condition)),
                                 false_node,
                                 false_node=None)
        return ConditionNode(node.addr, node.reaching_condition, node.condition, true_node, false_node=false_node)

    def _handle_CascadingCondition(self, node: CascadingConditionNode, **kwargs):

        new_cond_and_nodes = [ ]
        for cond, child_node in node.condition_and_nodes:
            new_node = self._walker._handle(child_node)
            if new_node is not None:
                new_cond_and_nodes.append((cond, new_node))

        new_else_node = None if node.else_node is None else self._walker._handle(node.else_node)

        if not new_cond_and_nodes and new_else_node is None:
            # empty node
            return None
        return CascadingConditionNode(node.addr, new_cond_and_nodes, else_node=new_else_node)

    def _handle_Loop(self, node, **kwargs):
        new_seq = self._walker._handle(node.sequence_node)

        if new_seq is None:
            return None

        result = node.copy()
        result.sequence_node = new_seq
        return result

    def _handle_SwitchCase(self, node, **kwargs):

        new_cases = { }

        for idx, case in node.cases.items():
            new_case = self._walker._handle(case)
            if new_case is not None:
                new_cases[idx] = new_case

        new_default_node = self._walker._handle(node.default_node)

        if not new_cases and new_default_node is None:
            return None

        return SwitchCaseNode(node.switch_expr,
                              new_cases,
                              new_default_node,
                              addr=node.addr
                              )

    @staticmethod
    def _handle_Default(node, **kwargs):
        return node

    @staticmethod
    def _handle_Block(block, **kwargs):
        if not block.statements:
            return None
        return block
