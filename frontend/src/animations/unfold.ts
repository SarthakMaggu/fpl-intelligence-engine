import type { Variants } from "framer-motion";

/* Card fade-in from left */
export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -24 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { type: "spring", stiffness: 260, damping: 26 },
  },
};

/* Card fade-in from right */
export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 24 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { type: "spring", stiffness: 260, damping: 26 },
  },
};

/* Player marker entrance */
export const playerVariants: Variants = {
  hidden: { scale: 0.6, opacity: 0 },
  visible: {
    scale: 1,
    opacity: 1,
    transition: {
      type: "spring",
      stiffness: 320,
      damping: 24,
    },
  },
};

/* Stagger container for player rows */
export const playerContainerVariants: Variants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.04,
      delayChildren: 0.15,
    },
  },
};

/* Player popup card */
export const popupVariants: Variants = {
  hidden: { opacity: 0, scale: 0.88, y: 8 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { type: "spring", stiffness: 420, damping: 26 },
  },
  exit: {
    opacity: 0,
    scale: 0.9,
    y: 6,
    transition: { duration: 0.12 },
  },
};

/* Loading dots */
export const loaderDotVariants: Variants = {
  idle: { scaleY: 0.4, opacity: 0.4 },
  loading: {
    scaleY: [0.4, 1.2, 0.4],
    opacity: [0.4, 1, 0.4],
    transition: { duration: 0.9, repeat: Infinity, ease: "easeInOut" },
  },
};

/* Kept for backwards compat (unused) */
export const napkinVariants = slideInLeft;
export const scratchpadVariants = slideInRight;
export const postItVariants = popupVariants;
export const inkDrawVariants: Variants = {
  hidden: { pathLength: 0, opacity: 0 },
  visible: { pathLength: 1, opacity: 1, transition: { duration: 0.55 } },
};
export const slideInVariants = slideInRight;
