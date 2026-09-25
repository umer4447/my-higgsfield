/**
 * Camera moves, as CSS classes.
 *
 * Motion assets are a real generated keyframe played under the move the preset
 * asks for. The frame is generated server-side; the move is a CSS transform,
 * which is why it is smooth at any size and costs nothing to scrub -- and why
 * the UI never calls it a video model. Swapping in a frame-by-frame model is a
 * change inside the backend's generation service; this file stays.
 */
export const MOVE_CLASS: Record<string, string> = {
  push: "mv mv-push",
  pull: "mv mv-pull",
  orbit: "mv mv-orbit",
  whip: "mv mv-whip",
  crane: "mv mv-crane",
  float: "mv mv-float",
  shake: "mv mv-shake",
  dolly: "mv mv-dolly",
};

export const MOVE_LABEL: Record<string, string> = {
  push: "Push in",
  pull: "Pull out",
  orbit: "Orbit",
  whip: "Whip pan",
  crane: "Crane up",
  float: "Float",
  shake: "Impact",
  dolly: "Dolly",
};
