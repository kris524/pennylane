# Copyright 2018-2022 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This submodule defines the symbolic operation that indicates the control of an operator.
"""

import warnings
from copy import copy

import numpy as np
from scipy import sparse

import pennylane as qml
from pennylane import math as qmlmath
from pennylane import operation
from pennylane.queuing import QueuingContext
from pennylane.wires import Wires


# pylint: disable=no-member
class ControlledOperation(operation.Operation):
    """Operation-specific methods and properties for the ``Controlled`` class.

    Dynamically mixed in based on the provided base operator.  If the base operator is an
    Operation, this class will be mixed in.

    When we no longer rely on certain functionality through `Operation`, we can get rid of this
    class.

    Defers inversion behavior to base.  This way we don't have to modify the ``Controlled.matrix``
    and ``Controlled.eigvals`` to account for in-place inversion. In-place inversion of a matrix
    """

    @property
    def _inverse(self):
        return False

    @_inverse.setter
    def _inverse(self, boolean):
        self.base._inverse = boolean  # pylint: disable=protected-access
        # refresh name as base_name got updated.
        self._name = f"C{self.base.name}"

    def inv(self):
        self.base.inv()
        # refresh name as base_name got updated.
        self._name = f"C{self.base.name}"
        return self

    @property
    def base_name(self):
        return f"C{self.base.base_name}"

    @property
    def name(self):
        return self._name

    @property
    def grad_method(self):
        return self.base.grad_method

    # pylint: disable=missing-function-docstring
    @property
    def basis(self):
        return self.base.basis

    @property
    def parameter_frequencies(self):
        if self.base.num_params == 1:
            try:
                base_gen = qml.generator(self.base, format="observable")
            except operation.GeneratorUndefinedError as e:
                raise operation.ParameterFrequenciesUndefinedError(
                    f"Operation {self.base.name} does not have parameter frequencies defined."
                ) from e

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    action="ignore", message=r".+ eigenvalues will be computed numerically\."
                )
                base_gen_eigvals = qml.eigvals(base_gen)

            # The projectors in the full generator add a eigenvsalue of `0` to
            # the eigenvalues of the base generator.
            gen_eigvals = np.append(base_gen_eigvals, 0)

            processed_gen_eigvals = tuple(np.round(gen_eigvals, 8))
            return [qml.gradients.eigvals_to_frequencies(processed_gen_eigvals)]
        raise operation.ParameterFrequenciesUndefinedError(
            f"Operation {self.name} does not have parameter frequencies defined, "
            "and parameter frequencies can not be computed via generator for more than one parameter."
        )


# pylint: disable=too-many-arguments, too-many-public-methods
class Controlled(operation.Operator):
    """Symbolic operator denoting a controlled operator.

    Args:
        base (~.operation.Operator): the operator that is controlled
        control_wires (Any): The wires to control on.

    Keyword Args:
        control_values (Iterable[Bool]): The values to control on. Must be the same
            length as ``control_wires``. Defaults to ``True`` for all control wires.
        work_wires (Any): Any auxiliary wires that can be used in the decomposition

    **Example:**

    >>> base = qml.RX(1.234, 2)
    >>> op = Controlled(base, (0,1))
    >>> op
    CRX(1.234, wires=[0, 1, 2])
    >>> op.base
    RX(1.234, wires=[2])
    >>> op.data
    [1.234]
    >>> op.wires
    <Wires = [0, 1, 2]>
    >>> op.control_wires
    <Wires = [0, 1]>
    >>> op.target_wires
    <Wires = [2]>
    >>> op.control_values
    [True, True]

    >>> op2 = Controlled(qml.PauliX(1), 0)
    >>> qml.matrix(op2)
    array([[1.+0.j, 0.+0.j, 0.+0.j, 0.+0.j],
           [0.+0.j, 1.+0.j, 0.+0.j, 0.+0.j],
           [0.+0.j, 0.+0.j, 0.+0.j, 1.+0.j],
           [0.+0.j, 0.+0.j, 1.+0.j, 0.+0.j]])
    >>> qml.eigvals(op2)
    tensor([ 1.,  1.,  1., -1.], requires_grad=True)
    >>> qml.generator(op)
    (Projector([1, 1], wires=[0, 1]) @ PauliX(wires=[2]), -0.5)
    >>> op.pow(-1.2)
    [CRX(-1.4808, wires=[0, 1, 2])]


    """

    _operation_type = None  # type if base inherits from operation and not observable
    _operation_observable_type = None  # type if base inherits from both operation and observable
    _observable_type = None  # type if base inherits from observable and not oepration

    # pylint: disable=unused-argument
    def __new__(
        cls, base, control_wires, control_values=None, work_wires=None, do_queue=True, id=None
    ):
        """Mixes in parents based on inheritance structure of base.

        Though all the types will be named "Pow", their *identity* and location in memory will be different
        based on ``base``'s inheritance.  We cache the different types in private class variables so that:

        """

        if isinstance(base, operation.Operation):
            if isinstance(base, operation.Observable):
                if cls._operation_observable_type is None:
                    base_classes = (
                        ControlledOperation,
                        Controlled,
                        operation.Observable,
                        operation.Operation,
                    )
                    cls._operation_observable_type = type(
                        "Controlled", base_classes, dict(cls.__dict__)
                    )
                return object.__new__(cls._operation_observable_type)

            # not an observable
            if cls._operation_type is None:
                base_classes = (ControlledOperation, Controlled, operation.Operation)
                cls._operation_type = type("Controlled", base_classes, dict(cls.__dict__))
            return object.__new__(cls._operation_type)

        if isinstance(base, operation.Observable):
            if cls._observable_type is None:
                base_classes = (Controlled, operation.Observable)
                cls._observable_type = type("Controlled", base_classes, dict(cls.__dict__))
            return object.__new__(cls._observable_type)

        return object.__new__(Controlled)

    # pylint: disable=attribute-defined-outside-init
    def __copy__(self):
        # this method needs to be overwritten becuase the base must be copied too.
        copied_op = object.__new__(type(self))
        # copied_op must maintain inheritance structure of self
        # For example, it must keep AdjointOperation if self has it
        # this way preserves inheritance structure

        for attr, value in vars(self).items():
            if attr != "_hyperparameters":
                setattr(copied_op, attr, value)
        copied_op._hyperparameters = copy(self._hyperparameters)
        copied_op._hyperparameters["base"] = copy(self.base)

        return copied_op

    # pylint: disable=super-init-not-called
    def __init__(
        self, base, control_wires, control_values=None, work_wires=None, do_queue=True, id=None
    ):
        control_wires = Wires(control_wires)
        if control_values is None:
            control_values = [True] * len(control_wires)
        else:
            if isinstance(control_values, str):
                warnings.warn(
                    "Specifying control values as a string is deprecated. Please use Sequence[Bool]",
                    UserWarning,
                )
                control_values = [(x == "1") for x in control_values]

            assert len(control_values) == len(
                control_wires
            ), "control_values should be the same length as control_wires"
            assert set(control_values).issubset(
                {False, True}
            ), "control_values can only take on True or False"

        assert (
            len(Wires.shared_wires([base.wires, control_wires])) == 0
        ), "The control wires must be different from the base operation wires."

        self.hyperparameters["base"] = base
        self.hyperparameters["control_wires"] = control_wires
        self.hyperparameters["control_values"] = control_values
        self.hyperparameters["work_wires"] = Wires([]) if work_wires is None else Wires(work_wires)

        self._name = f"C{base.name}"

        self._id = id
        self.queue_idx = None

        if do_queue:
            self.queue()

    @property
    def base(self):
        """The Operator being controlled."""
        return self.hyperparameters["base"]

    # Properties on the parameters ###########################

    @property
    def data(self):
        """Trainable parameters that the operator depends on."""
        return self.base.data

    @data.setter
    def data(self, new_data):
        self.base.data = new_data

    @property
    def parameters(self):
        return self.base.parameters

    @property
    def num_params(self):
        return self.base.num_params

    @property
    def batch_size(self):
        return self.base.batch_size

    @property
    def ndim_params(self):
        return self.base.ndim_params

    # Properties on the control values ######################
    @property
    def control_values(self):
        """Iterable[Bool]. For each control wire, denotes whether to control on ``True`` or ``False``."""
        return self.hyperparameters["control_values"]

    @property
    def _control_int(self):
        """Int. Conversion of ``control_values`` to an integer."""
        return sum(2**i for i, val in enumerate(reversed(self.control_values)) if val)

    # Properties on the wires ##########################

    @property
    def control_wires(self):
        """The control wires."""
        return self.hyperparameters["control_wires"]

    @property
    def target_wires(self):
        """The wires of the target operator."""
        return self.base.wires

    @property
    def work_wires(self):
        """Additional wires that can be used in the decomposition. Not modified by the operation."""
        return self.hyperparameters["work_wires"]

    @property
    def wires(self):
        return self.control_wires + self.base.wires + self.work_wires

    # pylint: disable=protected-access
    @property
    def _wires(self):
        return self.wires

    # pylint: disable=protected-access
    @_wires.setter
    def _wires(self, new_wires):
        new_wires = new_wires if isinstance(new_wires, Wires) else Wires(new_wires)

        num_control = len(self.control_wires)
        num_base = len(self.base.wires)
        num_control_and_base = num_control + num_base

        assert num_control_and_base <= len(new_wires), (
            f"{self.name} needs at least {num_control_and_base} wires."
            f" {len(new_wires)} provided."
        )

        self.hyperparameters["control_wires"] = new_wires[0:num_control]

        self.base._wires = new_wires[num_control:num_control_and_base]

        if len(new_wires) > num_control_and_base:
            self.hyperparameters["work_wires"] = new_wires[num_control_and_base:]
        else:
            self.hyperparameters["work_wires"] = Wires([])

    @property
    def num_wires(self):
        return len(self.wires)

    # Operator Properties #####################################

    @property
    def is_hermitian(self):
        return self.base.is_hermitian

    # pylint: disable=invalid-overridden-method
    @property
    def has_matrix(self):
        return self.base.has_matrix

    @property
    def _queue_category(self):
        """Used for sorting objects into their respective lists in `QuantumTape` objects.

        This property is a temporary solution that should not exist long-term and should not be
        used outside of ``QuantumTape._process_queue``.

        Returns ``_queue_cateogory`` for base operator.

        Options are:
            * `"_prep"`
            * `"_ops"`
            * `"_measurements"`
            * `None`
        """
        return self.base._queue_category  # pylint: disable=protected-access

    # Methods ##########################################

    def queue(self, context=QueuingContext):
        context.safe_update_info(self.base, owner=self)
        context.append(self, owns=self.base)
        return self

    def label(self, decimals=None, base_label=None, cache=None):
        return self.base.label(decimals=decimals, base_label=base_label, cache=cache)

    def matrix(self, wire_order=None):

        base_matrix = self.base.matrix()
        interface = qmlmath.get_interface(base_matrix)

        num_target_states = 2 ** len(self.target_wires)
        num_control_states = 2 ** len(self.control_wires)
        total_matrix_size = num_control_states * num_target_states

        padding_left = self._control_int * num_target_states
        padding_right = total_matrix_size - padding_left - num_target_states

        left_pad = qmlmath.cast_like(qmlmath.eye(padding_left, like=interface), 1j)
        right_pad = qmlmath.cast_like(qmlmath.eye(padding_right, like=interface), 1j)

        canonical_matrix = qmlmath.block_diag([left_pad, base_matrix, right_pad])

        if wire_order is None or self.wires == Wires(wire_order):
            return canonical_matrix

        active_wires = self.control_wires + self.target_wires
        return operation.expand_matrix(canonical_matrix, wires=active_wires, wire_order=wire_order)

    # pylint: disable=arguments-differ
    def sparse_matrix(self, wire_order=None, format="csr"):
        if wire_order is not None:
            raise NotImplementedError("wire_order argument is not yet implemented.")

        try:
            target_mat = self.base.sparse_matrix()
        except operation.SparseMatrixUndefinedError:
            try:
                target_mat = sparse.lil_matrix(self.base.matrix())
            except operation.MatrixUndefinedError as e:
                raise operation.SparseMatrixUndefinedError from e

        num_target_states = 2 ** len(self.target_wires)
        num_control_states = 2 ** len(self.control_wires)
        total_states = num_target_states * num_control_states

        start_ind = self._control_int * num_target_states
        end_ind = start_ind + num_target_states

        m = sparse.eye(total_states, format="lil", dtype=target_mat.dtype)

        m[start_ind:end_ind, start_ind:end_ind] = target_mat

        return m.asformat(format=format)

    def eigvals(self):
        base_eigvals = self.base.eigvals()
        num_target_wires = len(self.target_wires)
        num_control_wires = len(self.control_wires)

        total = 2 ** (num_target_wires + num_control_wires)
        ones = np.ones(total - len(base_eigvals))

        return qmlmath.concatenate([ones, base_eigvals])

    def diagonalizing_gates(self):
        return self.base.diagonalizing_gates()

    def decomposition(self):
        if not all(self.control_values):
            d = [
                qml.PauliX(w) for w, val in zip(self.control_wires, self.control_values) if not val
            ]
            d += [Controlled(self.base, self.control_wires, work_wires=self.work_wires)]
            d += [
                qml.PauliX(w) for w, val in zip(self.control_wires, self.control_values) if not val
            ]

            return d
        # More to come.  This will be an extensive PR in and of itself.
        return super().decomposition()

    def generator(self):
        sub_gen = self.base.generator()
        proj_tensor = operation.Tensor(*(qml.Projector([1], wires=w) for w in self.control_wires))
        return 1.0 * proj_tensor @ sub_gen

    def adjoint(self):
        return Controlled(
            self.base.adjoint(), self.control_wires, self.control_values, self.work_wires
        )

    def pow(self, z):
        base_pow = self.base.pow(z)
        return [
            Controlled(op, self.control_wires, self.control_values, self.work_wires)
            for op in base_pow
        ]
