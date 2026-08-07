from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class JunctionStructuredSetOutput:
    selected_members: torch.Tensor
    stopped: torch.Tensor
    sequence_log_probability: torch.Tensor


class JunctionStructuredSetDecoder(nn.Module):
    """Decode one complete Node/Road member set with an explicit STOP action."""

    def __init__(
        self,
        hidden_dim: int,
        *,
        dropout: float,
        max_steps: int,
        relation_dim: int = 0,
    ) -> None:
        super().__init__()
        if hidden_dim < 1 or max_steps < 1 or relation_dim < 0:
            raise ValueError("junction structured set decoder shape is invalid")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("junction structured set decoder dropout is invalid")
        self.max_steps = max_steps
        self.relation_dim = relation_dim
        self.member_key = nn.Linear(hidden_dim, hidden_dim)
        self.query_init = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        self.member_score = nn.Sequential(
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.stop_score = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.query_update = nn.GRUCell(hidden_dim, hidden_dim)
        self.relation_stem = (
            nn.Sequential(
                nn.Linear(relation_dim, hidden_dim),
                nn.GELU(),
                nn.LayerNorm(hidden_dim),
            )
            if relation_dim
            else None
        )

    def greedy_decode(
        self,
        members: torch.Tensor,
        member_mask: torch.Tensor,
        context: torch.Tensor,
        *,
        minimum_members: torch.Tensor | None = None,
        maximum_members: torch.Tensor | None = None,
        relation_index: torch.Tensor | None = None,
        relation_features: torch.Tensor | None = None,
        relation_mask: torch.Tensor | None = None,
    ) -> JunctionStructuredSetOutput:
        self._validate_inputs(members, member_mask, context)
        batch_size, member_count, _ = members.shape
        minimum_members, maximum_members = self._selection_bounds(
            member_mask,
            minimum_members,
            maximum_members,
        )
        selected = torch.zeros_like(member_mask)
        stopped = torch.zeros(batch_size, dtype=torch.bool, device=members.device)
        log_probability = torch.zeros(
            batch_size,
            dtype=members.dtype,
            device=members.device,
        )
        state = self.query_init(context)
        member_keys = self.member_key(members)
        relation_index, relation_hidden, relation_mask = self._relation_inputs(
            members,
            relation_index,
            relation_features,
            relation_mask,
        )
        for _ in range(min(self.max_steps, member_count + 1)):
            logits = self._step_logits(
                member_keys,
                member_mask,
                selected,
                state,
                relation_index,
                relation_hidden,
                relation_mask,
            )
            selected_count = selected.sum(dim=1)
            minimum = torch.finfo(logits.dtype).min
            logits[:, member_count] = logits[:, member_count].masked_fill(
                selected_count < minimum_members,
                minimum,
            )
            logits[:, :member_count] = logits[:, :member_count].masked_fill(
                (selected_count >= maximum_members).unsqueeze(1),
                minimum,
            )
            step_log_probability = logits.log_softmax(dim=-1)
            choice = step_log_probability.argmax(dim=-1)
            active = ~stopped
            log_probability = log_probability + torch.where(
                active,
                step_log_probability.gather(1, choice.unsqueeze(1)).squeeze(1),
                torch.zeros_like(log_probability),
            )
            chose_stop = choice.eq(member_count)
            chose_member = active & ~chose_stop
            safe_choice = choice.clamp_max(member_count - 1)
            one_hot = torch.nn.functional.one_hot(
                safe_choice,
                num_classes=member_count,
            ).bool()
            new_member = one_hot & chose_member.unsqueeze(-1)
            selected |= new_member
            state = self._advance(state, members, safe_choice, chose_member)
            stopped |= active & chose_stop
            if bool(stopped.all()):
                break
        return JunctionStructuredSetOutput(
            selected_members=selected,
            stopped=stopped,
            sequence_log_probability=log_probability,
        )

    def teacher_forced_loss_by_row(
        self,
        members: torch.Tensor,
        member_mask: torch.Tensor,
        context: torch.Tensor,
        acceptable_sets: torch.Tensor,
        acceptable_set_mask: torch.Tensor,
        task_mask: torch.Tensor,
        *,
        relation_index: torch.Tensor | None = None,
        relation_features: torch.Tensor | None = None,
        relation_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Marginalize acceptable sets while choosing only Gold members as teachers."""
        self._validate_inputs(members, member_mask, context)
        if acceptable_sets.ndim != 3 or acceptable_sets.shape[::2] != (
            members.shape[0],
            members.shape[1],
        ):
            raise ValueError("junction structured acceptable set shape differs")
        if acceptable_set_mask.shape != acceptable_sets.shape[:2]:
            raise ValueError("junction structured acceptable option mask differs")
        if task_mask.shape != (members.shape[0],):
            raise ValueError("junction structured task mask differs")
        if acceptable_sets.dtype is not torch.bool:
            raise ValueError("junction structured acceptable sets must be bool")
        valid_options = acceptable_set_mask & task_mask.unsqueeze(1)
        option_count = acceptable_sets.shape[1]
        expanded_members = members.unsqueeze(1).expand(
            -1, option_count, -1, -1
        ).reshape(-1, members.shape[1], members.shape[2])
        expanded_mask = member_mask.unsqueeze(1).expand(
            -1, option_count, -1
        ).reshape(-1, members.shape[1])
        expanded_context = context.unsqueeze(1).expand(
            -1, option_count, -1
        ).reshape(-1, context.shape[1])
        relation_index, relation_hidden, relation_mask = self._relation_inputs(
            members,
            relation_index,
            relation_features,
            relation_mask,
        )
        if relation_index is not None:
            relation_index = relation_index.unsqueeze(1).expand(
                -1, option_count, -1, -1
            ).reshape(-1, relation_index.shape[1], 2)
            relation_hidden = relation_hidden.unsqueeze(1).expand(
                -1, option_count, -1, -1
            ).reshape(-1, relation_hidden.shape[1], relation_hidden.shape[2])
            relation_mask = relation_mask.unsqueeze(1).expand(
                -1, option_count, -1
            ).reshape(-1, relation_mask.shape[1])
        targets = acceptable_sets.reshape(-1, members.shape[1])
        option_valid = valid_options.reshape(-1)
        option_loss = self._teacher_option_loss(
            expanded_members,
            expanded_mask,
            expanded_context,
            targets,
            option_valid,
            relation_index,
            relation_hidden,
            relation_mask,
        ).reshape(members.shape[0], option_count)
        maximum = torch.finfo(option_loss.dtype).max
        option_loss = option_loss.masked_fill(~valid_options, maximum)
        result = self.stop_score(context).squeeze(-1).float() * 0.0
        active = valid_options.any(dim=1)
        if bool(active.any()):
            active_loss = option_loss[active]
            result[active] = -torch.logsumexp(-active_loss, dim=1) + torch.log(
                valid_options[active].sum(dim=1).to(active_loss.dtype)
            )
        return result

    def _teacher_option_loss(
        self,
        members: torch.Tensor,
        member_mask: torch.Tensor,
        context: torch.Tensor,
        target: torch.Tensor,
        option_valid: torch.Tensor,
        relation_index: torch.Tensor | None,
        relation_hidden: torch.Tensor | None,
        relation_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        batch_size, member_count, _ = members.shape
        selected = torch.zeros_like(member_mask)
        state = self.query_init(context)
        member_keys = self.member_key(members)
        total = torch.zeros(batch_size, dtype=members.dtype, device=members.device)
        steps = torch.zeros_like(total)
        maximum_steps = min(self.max_steps, int(target.sum(dim=1).max().item()) + 1)
        for _ in range(maximum_steps):
            remaining = target & ~selected
            active = option_valid & (remaining.any(dim=1) | target.eq(selected).all(dim=1))
            logits = self._step_logits(
                member_keys,
                member_mask,
                selected,
                state,
                relation_index,
                relation_hidden,
                relation_mask,
            )
            log_probability = logits.log_softmax(dim=-1)
            allowed = torch.cat(
                (remaining, ~remaining.any(dim=1, keepdim=True)),
                dim=1,
            )
            allowed_log_probability = log_probability.masked_fill(
                ~allowed,
                torch.finfo(log_probability.dtype).min,
            )
            step_loss = -torch.logsumexp(allowed_log_probability, dim=1)
            total = total + torch.where(active, step_loss, torch.zeros_like(step_loss))
            steps = steps + active.to(steps.dtype)
            has_remaining = active & remaining.any(dim=1)
            teacher_logits = logits[:, :member_count].masked_fill(
                ~remaining,
                torch.finfo(logits.dtype).min,
            )
            teacher_choice = teacher_logits.argmax(dim=1)
            one_hot = torch.nn.functional.one_hot(
                teacher_choice,
                num_classes=member_count,
            ).bool()
            selected |= one_hot & has_remaining.unsqueeze(1)
            state = self._advance(
                state,
                members,
                teacher_choice,
                has_remaining,
            )
            if not bool(has_remaining.any()):
                break
        return total / steps.clamp_min(1.0)

    def _step_logits(
        self,
        member_keys: torch.Tensor,
        member_mask: torch.Tensor,
        selected: torch.Tensor,
        state: torch.Tensor,
        relation_index: torch.Tensor | None,
        relation_hidden: torch.Tensor | None,
        relation_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        relation_context = self._relation_context(
            member_keys,
            member_mask,
            selected,
            relation_index,
            relation_hidden,
            relation_mask,
        )
        member_logits = self.member_score(
            member_keys + state.unsqueeze(1) + relation_context
        ).squeeze(-1)
        member_logits = member_logits.masked_fill(
            ~member_mask | selected,
            torch.finfo(member_logits.dtype).min,
        )
        return torch.cat((member_logits, self.stop_score(state)), dim=1)

    def _relation_inputs(
        self,
        members: torch.Tensor,
        relation_index: torch.Tensor | None,
        relation_features: torch.Tensor | None,
        relation_mask: torch.Tensor | None,
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None]:
        values = (relation_index, relation_features, relation_mask)
        if self.relation_stem is None:
            if any(value is not None for value in values):
                raise ValueError(
                    "junction decoder received relations without relation conditioning"
                )
            return None, None, None
        if any(value is None for value in values):
            raise ValueError("junction decoder relation tensors are incomplete")
        if relation_index.ndim != 3 or relation_index.shape[-1] != 2:
            raise ValueError("junction decoder relation index shape differs")
        if relation_features.shape[:2] != relation_index.shape[:2]:
            raise ValueError("junction decoder relation feature scope differs")
        if relation_features.shape[-1] != self.relation_dim:
            raise ValueError("junction decoder relation feature dimension differs")
        if relation_mask.shape != relation_index.shape[:2]:
            raise ValueError("junction decoder relation mask shape differs")
        if relation_mask.dtype is not torch.bool:
            raise ValueError("junction decoder relation mask must be bool")
        if relation_index.shape[0] != members.shape[0]:
            raise ValueError("junction decoder relation batch scope differs")
        invalid = relation_index.lt(0) | relation_index.ge(members.shape[1])
        if bool((invalid & relation_mask.unsqueeze(-1)).any()):
            raise ValueError("junction decoder relation index is out of range")
        return relation_index, self.relation_stem(relation_features), relation_mask

    @staticmethod
    def _relation_context(
        members: torch.Tensor,
        member_mask: torch.Tensor,
        selected: torch.Tensor,
        relation_index: torch.Tensor | None,
        relation_hidden: torch.Tensor | None,
        relation_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        if relation_index is None:
            return torch.zeros_like(members)
        if relation_hidden is None or relation_mask is None:
            raise AssertionError("junction decoder encoded relations are incomplete")
        member_count = members.shape[1]
        safe_index = relation_index.clamp(0, member_count - 1)
        source_index = safe_index[..., 0]
        target_index = safe_index[..., 1]
        valid = (
            relation_mask
            & torch.gather(selected, 1, source_index)
            & torch.gather(member_mask, 1, target_index)
        )
        messages = relation_hidden.to(members.dtype) * valid.unsqueeze(-1).to(
            members.dtype
        )
        target_gather = target_index.unsqueeze(-1).expand_as(messages)
        aggregate = torch.zeros_like(members)
        aggregate.scatter_add_(1, target_gather, messages)
        degree = members.new_zeros(members.shape[0], member_count, 1)
        degree.scatter_add_(
            1,
            target_index.unsqueeze(-1),
            valid.unsqueeze(-1).to(members.dtype),
        )
        return aggregate / degree.clamp_min(1.0)

    def _advance(
        self,
        state: torch.Tensor,
        members: torch.Tensor,
        choice: torch.Tensor,
        active: torch.Tensor,
    ) -> torch.Tensor:
        selected_member = members.gather(
            1,
            choice.unsqueeze(1).unsqueeze(2).expand(-1, 1, members.shape[2]),
        ).squeeze(1)
        updated = self.query_update(selected_member, state)
        return torch.where(active.unsqueeze(1), updated, state)

    @staticmethod
    def _selection_bounds(
        member_mask: torch.Tensor,
        minimum_members: torch.Tensor | None,
        maximum_members: torch.Tensor | None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        batch_size = member_mask.shape[0]
        device = member_mask.device
        valid_count = member_mask.sum(dim=1)
        minimum = (
            torch.zeros(batch_size, dtype=torch.long, device=device)
            if minimum_members is None
            else minimum_members.to(device=device, dtype=torch.long)
        )
        maximum = (
            valid_count
            if maximum_members is None
            else maximum_members.to(device=device, dtype=torch.long)
        )
        if minimum.shape != (batch_size,) or maximum.shape != (batch_size,):
            raise ValueError("junction structured selection bounds differ")
        if bool((minimum < 0).any()) or bool((maximum < minimum).any()):
            raise ValueError("junction structured selection bounds are invalid")
        if bool((maximum > valid_count).any()):
            raise ValueError("junction structured maximum exceeds valid members")
        return minimum, maximum

    @staticmethod
    def _validate_inputs(
        members: torch.Tensor,
        member_mask: torch.Tensor,
        context: torch.Tensor,
    ) -> None:
        if members.ndim != 3 or member_mask.shape != members.shape[:2]:
            raise ValueError("junction structured member tensor shape differs")
        if context.shape != (members.shape[0], members.shape[2]):
            raise ValueError("junction structured context shape differs")
        if member_mask.dtype is not torch.bool:
            raise ValueError("junction structured member mask must be bool")
        if members.shape[1] < 1:
            raise ValueError("junction structured decoder requires member slots")


__all__ = [
    "JunctionStructuredSetDecoder",
    "JunctionStructuredSetOutput",
]
