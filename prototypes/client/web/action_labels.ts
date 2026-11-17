import type { GameplayAction } from "./command_input";
import type { ActionKind } from "./gameplay";

const actionLabels: Record<ActionKind, string> = {
  move_wait: "Move & Wait",
  attack: "Attack in place",
  move_attack: "Attack",
  move_capture: "Capture",
  join: "Join units",
  supply: "Supply",
  dive: "Dive",
  rise: "Rise",
  silo_launch: "Launch missile",
  load: "Load",
  unload: "Unload",
  purchase: "Purchase unit",
  activate_normal_power: "Activate normal Power",
  activate_super_power: "Activate Super Power",
  end_turn: "End turn",
  surrender: "Surrender",
};

export const waitLabel = (steps: number) =>
  steps > 0 ? "Move & Wait" : "Wait";
export function actionLabel(action: GameplayAction): string {
  return action.kind === "move_wait"
    ? waitLabel(action.path.length)
    : actionLabels[action.kind];
}
