import { useCallback, useEffect, useRef, useState } from 'react';

/** True while the media query matches. Used to apply desktop-only inline sizing. */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e) => setMatches(e.matches);
    mql.addEventListener('change', onChange);
    setMatches(mql.matches);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

/**
 * Drag-to-resize for a panel docked to one edge.
 *
 * `axis: 'x'` measures from the right edge of the window (a right-hand drawer),
 * `axis: 'y'` measures from the bottom (a bottom sheet on small screens).
 *
 * Returns the current size, whether a drag is in progress, and the props to
 * spread onto the grab handle. The handle is keyboard-operable: focus it and
 * use the arrow keys, Home and End.
 */
export function useDragResize({
  initial = 340,
  min = 260,
  max = 720,
  axis = 'x',
  step = 24,
  storageKey,
} = {}) {
  const [size, setSize] = useState(() => {
    if (storageKey && typeof window !== 'undefined') {
      const saved = Number(window.sessionStorage.getItem(storageKey));
      if (saved >= min && saved <= max) return saved;
    }
    return initial;
  });
  const [dragging, setDragging] = useState(false);
  const draggingRef = useRef(false);

  const clamp = useCallback((v) => Math.min(max, Math.max(min, v)), [min, max]);

  const commit = useCallback(
    (next) => {
      const v = clamp(next);
      setSize(v);
      if (storageKey) window.sessionStorage.setItem(storageKey, String(v));
    },
    [clamp, storageKey]
  );

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return;
      e.preventDefault();
      commit(axis === 'x' ? window.innerWidth - e.clientX : window.innerHeight - e.clientY);
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      setDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('pointermove', onMove, { passive: false });
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
  }, [axis, commit]);

  const onPointerDown = (e) => {
    e.preventDefault();
    draggingRef.current = true;
    setDragging(true);
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
  };

  const onKeyDown = (e) => {
    const grow = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
    const shrink = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
    if (e.key === grow) commit(size + step);
    else if (e.key === shrink) commit(size - step);
    else if (e.key === 'Home') commit(max);
    else if (e.key === 'End') commit(min);
    else return;
    e.preventDefault();
  };

  return {
    size,
    dragging,
    setSize: commit,
    handleProps: {
      onPointerDown,
      onKeyDown,
      role: 'separator',
      tabIndex: 0,
      'aria-orientation': axis === 'x' ? 'vertical' : 'horizontal',
      'aria-valuenow': Math.round(size),
      'aria-valuemin': min,
      'aria-valuemax': max,
      'aria-label': 'Resize the map panel',
    },
  };
}
