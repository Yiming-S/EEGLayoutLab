import type { components } from '../../contracts/generated/openapi';

type Schemas = components['schemas'];

/** Generated from eeglayoutlab.schemas.coordinate_source (contracts/README.md); validateCoordinateSource checks the same rules. */
export type MniConversion = Schemas['MniConversion'];
export type CoordinateConversion = Schemas['MniConversion'] | Schemas['LabelConversion'] | Schemas['HeadRegistration'];
export type RegionAssignment = Schemas['FileRegionAssignment'] | Schemas['BalancedRegionAssignment'];
/** `/1` an Ernie-native file; `/2` a converted input; `/3` adds how the regions were assigned (conversion null for an Ernie-native input). */
export type CoordinateSourceMetadata = Schemas['CoordinateSource'];
