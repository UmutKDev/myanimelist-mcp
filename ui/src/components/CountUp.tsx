import { useEffect, useState } from "react";
import { animate, useReducedMotion } from "motion/react";

/** Animated number that counts from 0 to `value` on mount. */
export function CountUp({
  value,
  decimals = 0,
  duration = 1,
  suffix = "",
}: {
  value: number;
  decimals?: number;
  duration?: number;
  suffix?: string;
}) {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(reduced ? value : 0);

  useEffect(() => {
    if (reduced) {
      setDisplay(value);
      return;
    }
    const controls = animate(0, value, {
      duration,
      ease: "easeOut",
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value, duration, reduced]);

  return (
    <span className="num">
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}
