/**
 * Tables that become cards below the md breakpoint instead of scrolling
 * sideways. Put `data-label` on every cell; the header row is kept for
 * assistive technology only.
 */
export const stackedTable = 'w-full text-left text-sm';
export const stackedHead = 'max-md:sr-only';
export const stackedBody = 'max-md:block';
export const stackedRow = 'max-md:block max-md:py-3';
export const stackedTitle = 'max-md:block max-md:pb-1';
export const stackedCell = 'max-md:flex max-md:items-start max-md:justify-between max-md:gap-3 max-md:py-1 max-md:text-right max-md:before:shrink-0 max-md:before:text-left max-md:before:text-xs max-md:before:font-normal max-md:before:text-muted-foreground max-md:before:content-[attr(data-label)] md:py-3 md:pr-3 md:align-top';
export const stackedAction = 'max-md:mt-2 max-md:block md:py-3';
