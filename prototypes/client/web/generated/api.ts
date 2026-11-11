export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ActionReadiness
         * @description Whether the current observation supports beginning a gameplay command.
         * @enum {string}
         */
        ActionReadiness: "ready" | "blocked" | "unknown";
        /** ActivateNormalPowerAction */
        ActivateNormalPowerAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "activate_normal_power";
        };
        /** ActivateSuperPowerAction */
        ActivateSuperPowerAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "activate_super_power";
        };
        /** ApiLimits */
        ApiLimits: {
            /**
             * Checkpoint Archive Bytes
             * @default 4259840
             * @constant
             */
            checkpoint_archive_bytes: 4259840;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Debug Max Frames
             * @default 600
             * @constant
             */
            debug_max_frames: 600;
            /**
             * Debug Read Bytes
             * @default 4096
             * @constant
             */
            debug_read_bytes: 4096;
            /**
             * Debug Write Bytes
             * @default 256
             * @constant
             */
            debug_write_bytes: 256;
            /**
             * Display Name Characters
             * @default 80
             * @constant
             */
            display_name_characters: 80;
            /**
             * Event Replay Bytes
             * @default 16777216
             * @constant
             */
            event_replay_bytes: 16777216;
            /**
             * Event Replay Count
             * @default 256
             * @constant
             */
            event_replay_count: 256;
            /**
             * Heartbeat Seconds
             * @default 15
             * @constant
             */
            heartbeat_seconds: 15;
            /**
             * Invitation Max Seconds
             * @default 3600
             * @constant
             */
            invitation_max_seconds: 3600;
            /**
             * Invitation Min Seconds
             * @default 60
             * @constant
             */
            invitation_min_seconds: 60;
            /**
             * Json Bytes
             * @default 65536
             * @constant
             */
            json_bytes: 65536;
            /**
             * Path Coordinates
             * @default 4096
             * @constant
             */
            path_coordinates: 4096;
            /**
             * Subscriber Bytes
             * @default 8388608
             * @constant
             */
            subscriber_bytes: 8388608;
            /**
             * Subscriber Event Count
             * @default 128
             * @constant
             */
            subscriber_event_count: 128;
        };
        /**
         * AttackAction
         * @description Attack a target from the unit's current position.
         */
        AttackAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "attack";
            target: components["schemas"]["Coordinate"];
            /** Unit Id */
            unit_id: string;
        };
        /**
         * BattleControlObservation
         * @description Battle controller fields from the same frame as the lifecycle signals.
         *
         *     Addresses for the supported ROM: mode is u32 at 0x03003F3C, state is
         *     u16 at 0x030032D8, lock_count is u8 at 0x030030F0, input_gate is i16
         *     at 0x030040E4, and input_state is u16 at 0x03003334 (little endian).
         *     These fields persist in menus and must not be used without engine checks.
         */
        BattleControlObservation: {
            /** Input Gate */
            input_gate: number;
            /** Input State */
            input_state: number;
            /** Lock Count */
            lock_count: number;
            /** Mode */
            mode: number;
            /** State */
            state: number;
        };
        /**
         * BattleDecodeSafety
         * @description Whether memory may be decoded as an active battle state.
         * @enum {string}
         */
        BattleDecodeSafety: "blocked" | "unknown";
        /** BattleState */
        BattleState: {
            /** Active Player Slot */
            active_player_slot: number;
            /**
             * @default {
             *       "reasons": [
             *         "CO effects option was not observed"
             *       ],
             *       "status": "unknown",
             *       "value": null
             *     }
             */
            co_effects_enabled: components["schemas"]["ObservedValue_bool_"];
            /** Day */
            day: number;
            /**
             * @default {
             *       "reasons": [
             *         "Fog option was not observed"
             *       ],
             *       "status": "unknown",
             *       "value": null
             *     }
             */
            fog_enabled: components["schemas"]["ObservedValue_bool_"];
            map: components["schemas"]["MapState"];
            /** Players */
            players: components["schemas"]["PlayerState"][];
            /** Properties */
            properties: components["schemas"]["PropertyState"][];
            /** Units */
            units: components["schemas"]["UnitState"][];
            weather: components["schemas"]["ObservedValue_Weather_"];
        };
        /** BattleValidationReport */
        BattleValidationReport: {
            /** Frame */
            frame: number;
            geometry: components["schemas"]["StructureValidation"];
            lifecycle: components["schemas"]["LifecycleAssessment"];
            /** Live Reasons */
            live_reasons: string[];
            players: components["schemas"]["StructureValidation"];
            properties: components["schemas"]["StructureValidation"];
            units: components["schemas"]["StructureValidation"];
        };
        /** CapabilitiesResponse */
        CapabilitiesResponse: {
            /**
             * Actions
             * @default []
             */
            actions: components["schemas"]["FeatureAvailability"][];
            /**
             * @default {
             *       "co_ids": [
             *         "nell",
             *         "andy",
             *         "max",
             *         "sami",
             *         "hachi",
             *         "olaf",
             *         "grit",
             *         "colin",
             *         "kanbei",
             *         "sonja",
             *         "sensei",
             *         "eagle",
             *         "drake",
             *         "jess",
             *         "flak",
             *         "lash",
             *         "adder",
             *         "hawke",
             *         "sturm"
             *       ],
             *       "combination_constraint": "verified_options",
             *       "contract_version": 1,
             *       "map_ids": [
             *         "bean_island",
             *         "crater_isle",
             *         "triangles",
             *         "ball_islands",
             *         "coral_lagoon",
             *         "puzzle_trio",
             *         "fist_peninsula",
             *         "deer_harbor",
             *         "alara_range",
             *         "lost_river",
             *         "volcano_isle",
             *         "turtle_atoll",
             *         "squash_island",
             *         "cube_keys",
             *         "mirror_islands",
             *         "shark_strait",
             *         "royal_channel",
             *         "little_island",
             *         "sun_canal",
             *         "beaker_river",
             *         "star_islands",
             *         "eon_springs",
             *         "portal_bridge",
             *         "sabre_range",
             *         "asphalt_maze",
             *         "cog_isle",
             *         "zero_wood",
             *         "switchback",
             *         "ruby_keys",
             *         "rainy_haven",
             *         "rail_strait",
             *         "tribe_islands",
             *         "vision_bridge",
             *         "piston_dam",
             *         "hat_harbor",
             *         "swan_cove",
             *         "go_islands",
             *         "hourglass_isle",
             *         "brace_range",
             *         "river_range",
             *         "moon_isle",
             *         "mint_plateau",
             *         "jewel_canal",
             *         "wrench_island",
             *         "rapid_ferry",
             *         "bundle_city",
             *         "scarab_road",
             *         "pointing_river",
             *         "liaison_wood",
             *         "big_daddy",
             *         "spann_island",
             *         "moji_island",
             *         "duo_falls",
             *         "sole_harbor",
             *         "pivot_isle",
             *         "lands_end",
             *         "kita_straight",
             *         "point_stormy",
             *         "ridge_island",
             *         "mials_hope",
             *         "bounty_river",
             *         "toil_ferry",
             *         "twin_isle",
             *         "dire_range",
             *         "egg_islands",
             *         "terra_maw",
             *         "pay_dirt",
             *         "long_road",
             *         "nest_egg",
             *         "the_trident",
             *         "banker_hills",
             *         "missile_plains",
             *         "delta_heights",
             *         "poem_cape",
             *         "blue_lake",
             *         "coil_range",
             *         "leaf_haven",
             *         "battle_cube",
             *         "grid_assault",
             *         "crossroad",
             *         "pyramid_cape",
             *         "bead_islands",
             *         "clover_keys",
             *         "keyhole_cove",
             *         "fork_river",
             *         "mantis_river",
             *         "channel_city",
             *         "ink_canal",
             *         "shield_hills",
             *         "peril_maze",
             *         "gem_creek",
             *         "glass_heights",
             *         "devils_inlet",
             *         "shear_port",
             *         "liars_cove",
             *         "nail_canal",
             *         "atlas_river",
             *         "eel_channels",
             *         "jab_peninsula",
             *         "thorn_islands",
             *         "portsmouth",
             *         "archipelagos",
             *         "wyrms_eye",
             *         "knotted_keys",
             *         "four_corners",
             *         "rocket_cape",
             *         "crop_river",
             *         "tween_isle",
             *         "rival_islands",
             *         "loop_road",
             *         "plus_canal",
             *         "islas_five",
             *         "patriot_cove",
             *         "web_river",
             *         "cap_narrows",
             *         "jay_islands",
             *         "chain_canal",
             *         "spring_lakes",
             *         "tatter_river",
             *         "island_x",
             *         "alakule",
             *         "traitor_river",
             *         "fable_hills",
             *         "south_cape",
             *         "glory_islands",
             *         "pipe_maze",
             *         "lock_ridge",
             *         "heartland",
             *         "badlands",
             *         "stamp_islands",
             *         "rivers_four",
             *         "ring_islands",
             *         "last_mission"
             *       ],
             *       "minimum_teams": 2,
             *       "player_counts": [
             *         2,
             *         3,
             *         4
             *       ],
             *       "players": [
             *         {
             *           "co_id": "andy",
             *           "color": "red",
             *           "contract_version": 1,
             *           "control": "external",
             *           "slot": "slot_1",
             *           "team_id": "a"
             *         },
             *         {
             *           "co_id": "max",
             *           "color": "blue",
             *           "contract_version": 1,
             *           "control": "external",
             *           "slot": "slot_2",
             *           "team_id": "b"
             *         }
             *       ],
             *       "rule_options": {
             *         "capture_limit": [
             *           null,
             *           12,
             *           13,
             *           14,
             *           15,
             *           16,
             *           17,
             *           18,
             *           19,
             *           20,
             *           21,
             *           22,
             *           23,
             *           24,
             *           25,
             *           26,
             *           27
             *         ],
             *         "co_powers": [
             *           true,
             *           false
             *         ],
             *         "contract_version": 1,
             *         "day_limit": [
             *           null,
             *           5,
             *           6,
             *           7,
             *           8,
             *           9,
             *           10,
             *           11,
             *           12,
             *           13,
             *           14,
             *           15,
             *           16,
             *           17,
             *           18,
             *           19,
             *           20,
             *           21,
             *           22,
             *           23,
             *           24,
             *           25,
             *           26,
             *           27,
             *           28,
             *           29,
             *           30,
             *           31,
             *           32,
             *           33,
             *           34,
             *           35,
             *           36,
             *           37,
             *           38,
             *           39,
             *           40,
             *           41,
             *           42,
             *           43,
             *           44,
             *           45,
             *           46,
             *           47,
             *           48,
             *           49,
             *           50,
             *           51,
             *           52,
             *           53,
             *           54,
             *           55,
             *           56,
             *           57,
             *           58,
             *           59,
             *           60,
             *           61,
             *           62,
             *           63,
             *           64,
             *           65,
             *           66,
             *           67,
             *           68,
             *           69,
             *           70,
             *           71,
             *           72,
             *           73,
             *           74,
             *           75,
             *           76,
             *           77,
             *           78,
             *           79,
             *           80,
             *           81,
             *           82,
             *           83,
             *           84,
             *           85,
             *           86,
             *           87,
             *           88,
             *           89,
             *           90,
             *           91,
             *           92,
             *           93,
             *           94,
             *           95,
             *           96,
             *           97,
             *           98,
             *           99
             *         ],
             *         "fog": [
             *           false,
             *           true
             *         ],
             *         "income_per_property": [
             *           1000,
             *           1500,
             *           2000,
             *           2500,
             *           3000,
             *           3500,
             *           4000,
             *           4500,
             *           5000
             *         ],
             *         "weather": [
             *           "clear",
             *           "rain",
             *           "snow",
             *           "random"
             *         ]
             *       },
             *       "rules": {
             *         "capture_limit": null,
             *         "co_powers": true,
             *         "contract_version": 1,
             *         "day_limit": 30,
             *         "fog": false,
             *         "income_per_property": 1000,
             *         "weather": "clear"
             *       },
             *       "team_ids": [
             *         "a",
             *         "b",
             *         "c",
             *         "d"
             *       ]
             *     }
             */
            configuration_options: components["schemas"]["ConfigurationOptions"];
            /**
             * Configuration Profiles
             * @default [
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "bean_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "bean_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "crater_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "crater_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "triangles",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "triangles_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "ball_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "ball_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "coral_lagoon",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "coral_lagoon_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "puzzle_trio",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "puzzle_trio_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "fist_peninsula",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "fist_peninsula_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "deer_harbor",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "deer_harbor_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "alara_range",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "alara_range_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "lost_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "lost_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "volcano_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "volcano_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "turtle_atoll",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "turtle_atoll_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "squash_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "squash_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "cube_keys",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "cube_keys_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "mirror_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "mirror_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "shark_strait",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "shark_strait_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "royal_channel",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "classic",
             *         "profile_id": "royal_channel_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "little_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "little_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "sun_canal",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "sun_canal_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "beaker_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "beaker_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "star_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "star_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "eon_springs",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "eon_springs_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "portal_bridge",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "portal_bridge_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "sabre_range",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "sabre_range_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "asphalt_maze",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "asphalt_maze_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "cog_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "cog_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "zero_wood",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "zero_wood_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "switchback",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "switchback_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "ruby_keys",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "ruby_keys_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "rainy_haven",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "rainy_haven_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "rail_strait",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "rail_strait_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "tribe_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "tribe_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "vision_bridge",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "vision_bridge_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "piston_dam",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "piston_dam_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "hat_harbor",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "hat_harbor_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "swan_cove",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "swan_cove_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "go_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "go_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "hourglass_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "versus",
             *         "profile_id": "hourglass_isle_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "brace_range",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "brace_range_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "river_range",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "river_range_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "moon_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "moon_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "mint_plateau",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "mint_plateau_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "jewel_canal",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "jewel_canal_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "wrench_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "wrench_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "rapid_ferry",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "rapid_ferry_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "bundle_city",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "bundle_city_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "scarab_road",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "scarab_road_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "pointing_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "pointing_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "liaison_wood",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "liaison_wood_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "big_daddy",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "big_daddy_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "spann_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "spann_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "moji_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "moji_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "duo_falls",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "duo_falls_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "sole_harbor",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "sole_harbor_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "pivot_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "pivot_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "lands_end",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "lands_end_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "kita_straight",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "kita_straight_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "point_stormy",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "point_stormy_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "ridge_island",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "ridge_island_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "mials_hope",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "mials_hope_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "bounty_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "bounty_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "toil_ferry",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "toil_ferry_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "twin_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "twin_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "dire_range",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "dire_range_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "egg_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "egg_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "terra_maw",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "terra_maw_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "pay_dirt",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "pay_dirt_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "long_road",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "long_road_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "nest_egg",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "nest_egg_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "the_trident",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "the_trident_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "banker_hills",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "banker_hills_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "missile_plains",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "missile_plains_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "delta_heights",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "delta_heights_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "poem_cape",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "poem_cape_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "blue_lake",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "blue_lake_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "coil_range",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "coil_range_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "leaf_haven",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "leaf_haven_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "battle_cube",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "battle_cube_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "grid_assault",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "grid_assault_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "crossroad",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "pre_deployed",
             *         "profile_id": "crossroad_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "pyramid_cape",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "pyramid_cape_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "bead_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "bead_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "clover_keys",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "clover_keys_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "keyhole_cove",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "keyhole_cove_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "fork_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "fork_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "mantis_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "mantis_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "channel_city",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "channel_city_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "ink_canal",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "ink_canal_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "shield_hills",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "shield_hills_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "peril_maze",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "peril_maze_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "gem_creek",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "gem_creek_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "glass_heights",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "glass_heights_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "devils_inlet",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "devils_inlet_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "shear_port",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "shear_port_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "liars_cove",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "liars_cove_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "nail_canal",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "nail_canal_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "atlas_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "atlas_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "eel_channels",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "eel_channels_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "jab_peninsula",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "jab_peninsula_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "thorn_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "thorn_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "portsmouth",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "portsmouth_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "archipelagos",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "archipelagos_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "wyrms_eye",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "wyrms_eye_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "knotted_keys",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "three_player",
             *         "profile_id": "knotted_keys_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "four_corners",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "four_corners_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "rocket_cape",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "rocket_cape_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "crop_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "crop_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "tween_isle",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "tween_isle_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "rival_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "rival_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "loop_road",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "loop_road_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "plus_canal",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "plus_canal_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "islas_five",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "islas_five_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "patriot_cove",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "patriot_cove_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "web_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "web_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "cap_narrows",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "cap_narrows_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "jay_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "jay_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "chain_canal",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "chain_canal_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "spring_lakes",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "spring_lakes_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "tatter_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "tatter_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "island_x",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "island_x_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "alakule",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "alakule_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "traitor_river",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "traitor_river_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "fable_hills",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "fable_hills_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "south_cape",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "south_cape_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "glory_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "glory_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "pipe_maze",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "pipe_maze_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "lock_ridge",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "lock_ridge_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "heartland",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "heartland_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "save_dependent",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "badlands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             },
             *             {
             *               "co_id": "flak",
             *               "color": "yellow",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_4",
             *               "team_id": "d"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "four_player",
             *         "profile_id": "badlands_v1",
             *         "requires_unlock": true
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "stamp_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "stamp_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "rivers_four",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "rivers_four_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "ring_islands",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "ring_islands_v1",
             *         "requires_unlock": false
             *       },
             *       {
             *         "availability": "always_available",
             *         "configuration": {
             *           "contract_version": 1,
             *           "map_id": "last_mission",
             *           "players": [
             *             {
             *               "co_id": "andy",
             *               "color": "red",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_1",
             *               "team_id": "a"
             *             },
             *             {
             *               "co_id": "max",
             *               "color": "blue",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_2",
             *               "team_id": "b"
             *             },
             *             {
             *               "co_id": "sami",
             *               "color": "green",
             *               "contract_version": 1,
             *               "control": "external",
             *               "slot": "slot_3",
             *               "team_id": "c"
             *             }
             *           ],
             *           "rules": {
             *             "capture_limit": null,
             *             "co_powers": true,
             *             "contract_version": 1,
             *             "day_limit": 30,
             *             "fog": false,
             *             "income_per_property": 1000,
             *             "weather": "clear"
             *           }
             *         },
             *         "contract_version": 1,
             *         "map_category": "war_room",
             *         "profile_id": "last_mission_v1",
             *         "requires_unlock": false
             *       }
             *     ]
             */
            configuration_profiles: components["schemas"]["ConfigurationProfile"][];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Debug Enabled
             * @default false
             */
            debug_enabled: boolean;
            /**
             * Debug Memory Regions
             * @default [
             *       [
             *         33554432,
             *         33816576
             *       ],
             *       [
             *         50331648,
             *         50364416
             *       ]
             *     ]
             */
            debug_memory_regions: [
                number,
                number
            ][];
            /**
             * Default Profile Id
             * @default bean_island_v1
             * @constant
             */
            default_profile_id: "bean_island_v1";
            http_sse: components["schemas"]["FeatureAvailability"];
            /**
             * @default {
             *       "checkpoint_archive_bytes": 4259840,
             *       "contract_version": 1,
             *       "debug_max_frames": 600,
             *       "debug_read_bytes": 4096,
             *       "debug_write_bytes": 256,
             *       "display_name_characters": 80,
             *       "event_replay_bytes": 16777216,
             *       "event_replay_count": 256,
             *       "heartbeat_seconds": 15,
             *       "invitation_max_seconds": 3600,
             *       "invitation_min_seconds": 60,
             *       "json_bytes": 65536,
             *       "path_coordinates": 4096,
             *       "subscriber_bytes": 8388608,
             *       "subscriber_event_count": 128
             *     }
             */
            limits: components["schemas"]["ApiLimits"];
            mcp_compatibility?: components["schemas"]["MCPCompatibility"];
            /**
             * @default {
             *       "available": false,
             *       "contract_version": 1,
             *       "implemented": false,
             *       "name": "mcp_resources",
             *       "unavailable_reason": "MCP game resources are not implemented",
             *       "verification": "unverified"
             *     }
             */
            mcp_resources: components["schemas"]["FeatureAvailability"];
            mcp_subscriptions: components["schemas"]["FeatureAvailability"];
            /**
             * Observation Visibility
             * @default omniscient_trusted_clients
             * @constant
             */
            observation_visibility: "omniscient_trusted_clients";
            /**
             * Operations
             * @default []
             */
            operations: components["schemas"]["FeatureAvailability"][];
            /**
             * Production Facilities
             * @default []
             */
            production_facilities: components["schemas"]["ProductionFacilityCapabilities"][];
            /**
             * Production Unit Types
             * @default []
             */
            production_unit_types: string[];
            /**
             * Supported Control Modes
             * @default [
             *       "external"
             *     ]
             */
            supported_control_modes: [
                "external"
            ];
            /**
             * Supported Game Contract Versions
             * @default [
             *       1
             *     ]
             */
            supported_game_contract_versions: 1[];
            /**
             * Supported Game State Schema Versions
             * @default [
             *       5
             *     ]
             */
            supported_game_state_schema_versions: number[];
            /**
             * Supported Match Observation Schema Versions
             * @default [
             *       1
             *     ]
             */
            supported_match_observation_schema_versions: number[];
            /**
             * Supported Player Counts
             * @default [
             *       2,
             *       3,
             *       4
             *     ]
             */
            supported_player_counts: [
                2,
                3,
                4
            ];
        };
        /** CargoDrop */
        CargoDrop: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            destination: components["schemas"]["Coordinate"];
            /** Unit Id */
            unit_id: string;
        };
        /**
         * CheckpointCompatibility
         * @description Safe metadata; excludes manifests' credential hashes and local paths.
         */
        CheckpointCompatibility: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Decoder Schema Version */
            decoder_schema_version: number;
            /** Emulator Build */
            emulator_build: string;
            /**
             * Emulator Mode
             * @enum {string}
             */
            emulator_mode: "headless" | "windowed";
            /** Observation Schema Version */
            observation_schema_version: number;
            /** Rom Sha256 */
            rom_sha256: string;
        };
        /** CheckpointListResponse */
        CheckpointListResponse: {
            /** Checkpoints */
            checkpoints: components["schemas"]["CheckpointReference"][];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
        };
        /** CheckpointReference */
        CheckpointReference: {
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            /** Revision */
            revision: number;
        };
        /** CheckpointResponse */
        CheckpointResponse: {
            checkpoint: components["schemas"]["CheckpointReference"];
            compatibility: components["schemas"]["CheckpointCompatibility"];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
        };
        /**
         * CloseMatchRequest
         * @description Closing is ordered after prior work and has no expected game revision.
         */
        CloseMatchRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** CommandReceipt */
        CommandReceipt: {
            /** Accepted Revision */
            accepted_revision: number;
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            status: components["schemas"]["CommandStatus"];
        };
        /** CommandResult */
        CommandResult: {
            /** Accepted Revision */
            accepted_revision: number;
            /**
             * Checkpoint Id
             * @default null
             */
            checkpoint_id: string | null;
            /**
             * Command Id
             * Format: uuid
             */
            command_id: string;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** @default null */
            error: components["schemas"]["ErrorBody"] | null;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * Resulting Revision
             * @default null
             */
            resulting_revision: number | null;
            status: components["schemas"]["CommandStatus"];
        };
        /**
         * CommandStatus
         * @enum {string}
         */
        CommandStatus: "queued" | "running" | "completed" | "rejected" | "rolled_back" | "recovery_required";
        /**
         * ConfigurationOptions
         * @description Accepted options derived from the verified profile, not the recognition catalog.
         */
        ConfigurationOptions: {
            /**
             * Co Ids
             * @default [
             *       "nell",
             *       "andy",
             *       "max",
             *       "sami",
             *       "hachi",
             *       "olaf",
             *       "grit",
             *       "colin",
             *       "kanbei",
             *       "sonja",
             *       "sensei",
             *       "eagle",
             *       "drake",
             *       "jess",
             *       "flak",
             *       "lash",
             *       "adder",
             *       "hawke",
             *       "sturm"
             *     ]
             */
            co_ids: ("nell" | "andy" | "max" | "sami" | "hachi" | "olaf" | "grit" | "colin" | "kanbei" | "sonja" | "sensei" | "eagle" | "drake" | "jess" | "flak" | "lash" | "adder" | "hawke" | "sturm")[];
            /**
             * Combination Constraint
             * @default verified_options
             * @constant
             */
            combination_constraint: "verified_options";
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Map Ids
             * @default [
             *       "bean_island",
             *       "crater_isle",
             *       "triangles",
             *       "ball_islands",
             *       "coral_lagoon",
             *       "puzzle_trio",
             *       "fist_peninsula",
             *       "deer_harbor",
             *       "alara_range",
             *       "lost_river",
             *       "volcano_isle",
             *       "turtle_atoll",
             *       "squash_island",
             *       "cube_keys",
             *       "mirror_islands",
             *       "shark_strait",
             *       "royal_channel",
             *       "little_island",
             *       "sun_canal",
             *       "beaker_river",
             *       "star_islands",
             *       "eon_springs",
             *       "portal_bridge",
             *       "sabre_range",
             *       "asphalt_maze",
             *       "cog_isle",
             *       "zero_wood",
             *       "switchback",
             *       "ruby_keys",
             *       "rainy_haven",
             *       "rail_strait",
             *       "tribe_islands",
             *       "vision_bridge",
             *       "piston_dam",
             *       "hat_harbor",
             *       "swan_cove",
             *       "go_islands",
             *       "hourglass_isle",
             *       "brace_range",
             *       "river_range",
             *       "moon_isle",
             *       "mint_plateau",
             *       "jewel_canal",
             *       "wrench_island",
             *       "rapid_ferry",
             *       "bundle_city",
             *       "scarab_road",
             *       "pointing_river",
             *       "liaison_wood",
             *       "big_daddy",
             *       "spann_island",
             *       "moji_island",
             *       "duo_falls",
             *       "sole_harbor",
             *       "pivot_isle",
             *       "lands_end",
             *       "kita_straight",
             *       "point_stormy",
             *       "ridge_island",
             *       "mials_hope",
             *       "bounty_river",
             *       "toil_ferry",
             *       "twin_isle",
             *       "dire_range",
             *       "egg_islands",
             *       "terra_maw",
             *       "pay_dirt",
             *       "long_road",
             *       "nest_egg",
             *       "the_trident",
             *       "banker_hills",
             *       "missile_plains",
             *       "delta_heights",
             *       "poem_cape",
             *       "blue_lake",
             *       "coil_range",
             *       "leaf_haven",
             *       "battle_cube",
             *       "grid_assault",
             *       "crossroad",
             *       "pyramid_cape",
             *       "bead_islands",
             *       "clover_keys",
             *       "keyhole_cove",
             *       "fork_river",
             *       "mantis_river",
             *       "channel_city",
             *       "ink_canal",
             *       "shield_hills",
             *       "peril_maze",
             *       "gem_creek",
             *       "glass_heights",
             *       "devils_inlet",
             *       "shear_port",
             *       "liars_cove",
             *       "nail_canal",
             *       "atlas_river",
             *       "eel_channels",
             *       "jab_peninsula",
             *       "thorn_islands",
             *       "portsmouth",
             *       "archipelagos",
             *       "wyrms_eye",
             *       "knotted_keys",
             *       "four_corners",
             *       "rocket_cape",
             *       "crop_river",
             *       "tween_isle",
             *       "rival_islands",
             *       "loop_road",
             *       "plus_canal",
             *       "islas_five",
             *       "patriot_cove",
             *       "web_river",
             *       "cap_narrows",
             *       "jay_islands",
             *       "chain_canal",
             *       "spring_lakes",
             *       "tatter_river",
             *       "island_x",
             *       "alakule",
             *       "traitor_river",
             *       "fable_hills",
             *       "south_cape",
             *       "glory_islands",
             *       "pipe_maze",
             *       "lock_ridge",
             *       "heartland",
             *       "badlands",
             *       "stamp_islands",
             *       "rivers_four",
             *       "ring_islands",
             *       "last_mission"
             *     ]
             */
            map_ids: ("delta_heights" | "poem_cape" | "blue_lake" | "coil_range" | "leaf_haven" | "battle_cube" | "grid_assault" | "crossroad" | "pyramid_cape" | "bead_islands" | "clover_keys" | "keyhole_cove" | "fork_river" | "mantis_river" | "channel_city" | "ink_canal" | "shield_hills" | "peril_maze" | "gem_creek" | "glass_heights" | "devils_inlet" | "shear_port" | "liars_cove" | "nail_canal" | "atlas_river" | "eel_channels" | "jab_peninsula" | "thorn_islands" | "portsmouth" | "archipelagos" | "wyrms_eye" | "knotted_keys" | "four_corners" | "rocket_cape" | "crop_river" | "tween_isle" | "rival_islands" | "loop_road" | "plus_canal" | "islas_five" | "patriot_cove" | "web_river" | "cap_narrows" | "jay_islands" | "chain_canal" | "spring_lakes" | "tatter_river" | "island_x" | "alakule" | "traitor_river" | "fable_hills" | "south_cape" | "glory_islands" | "pipe_maze" | "lock_ridge" | "heartland" | "badlands" | "stamp_islands" | "rivers_four" | "ring_islands" | "last_mission" | "bean_island" | "crater_isle" | "triangles" | "ball_islands" | "coral_lagoon" | "puzzle_trio" | "fist_peninsula" | "deer_harbor" | "alara_range" | "lost_river" | "volcano_isle" | "turtle_atoll" | "squash_island" | "cube_keys" | "mirror_islands" | "shark_strait" | "royal_channel" | "little_island" | "sun_canal" | "beaker_river" | "star_islands" | "eon_springs" | "portal_bridge" | "sabre_range" | "asphalt_maze" | "cog_isle" | "zero_wood" | "switchback" | "ruby_keys" | "rainy_haven" | "rail_strait" | "tribe_islands" | "vision_bridge" | "piston_dam" | "hat_harbor" | "swan_cove" | "go_islands" | "hourglass_isle" | "brace_range" | "river_range" | "moon_isle" | "mint_plateau" | "jewel_canal" | "wrench_island" | "rapid_ferry" | "bundle_city" | "scarab_road" | "pointing_river" | "liaison_wood" | "big_daddy" | "spann_island" | "moji_island" | "duo_falls" | "sole_harbor" | "pivot_isle" | "lands_end" | "kita_straight" | "point_stormy" | "ridge_island" | "mials_hope" | "bounty_river" | "toil_ferry" | "twin_isle" | "dire_range" | "egg_islands" | "terra_maw" | "pay_dirt" | "long_road" | "nest_egg" | "the_trident" | "banker_hills" | "missile_plains")[];
            /**
             * Minimum Teams
             * @default 2
             * @constant
             */
            minimum_teams: 2;
            /**
             * Player Counts
             * @default [
             *       2,
             *       3,
             *       4
             *     ]
             */
            player_counts: [
                2,
                3,
                4
            ];
            /**
             * Players
             * @default [
             *       {
             *         "co_id": "andy",
             *         "color": "red",
             *         "contract_version": 1,
             *         "control": "external",
             *         "slot": "slot_1",
             *         "team_id": "a"
             *       },
             *       {
             *         "co_id": "max",
             *         "color": "blue",
             *         "contract_version": 1,
             *         "control": "external",
             *         "slot": "slot_2",
             *         "team_id": "b"
             *       }
             *     ]
             */
            players: components["schemas"]["PlayerConfiguration"][];
            /**
             * @default {
             *       "capture_limit": [
             *         null,
             *         12,
             *         13,
             *         14,
             *         15,
             *         16,
             *         17,
             *         18,
             *         19,
             *         20,
             *         21,
             *         22,
             *         23,
             *         24,
             *         25,
             *         26,
             *         27
             *       ],
             *       "co_powers": [
             *         true,
             *         false
             *       ],
             *       "contract_version": 1,
             *       "day_limit": [
             *         null,
             *         5,
             *         6,
             *         7,
             *         8,
             *         9,
             *         10,
             *         11,
             *         12,
             *         13,
             *         14,
             *         15,
             *         16,
             *         17,
             *         18,
             *         19,
             *         20,
             *         21,
             *         22,
             *         23,
             *         24,
             *         25,
             *         26,
             *         27,
             *         28,
             *         29,
             *         30,
             *         31,
             *         32,
             *         33,
             *         34,
             *         35,
             *         36,
             *         37,
             *         38,
             *         39,
             *         40,
             *         41,
             *         42,
             *         43,
             *         44,
             *         45,
             *         46,
             *         47,
             *         48,
             *         49,
             *         50,
             *         51,
             *         52,
             *         53,
             *         54,
             *         55,
             *         56,
             *         57,
             *         58,
             *         59,
             *         60,
             *         61,
             *         62,
             *         63,
             *         64,
             *         65,
             *         66,
             *         67,
             *         68,
             *         69,
             *         70,
             *         71,
             *         72,
             *         73,
             *         74,
             *         75,
             *         76,
             *         77,
             *         78,
             *         79,
             *         80,
             *         81,
             *         82,
             *         83,
             *         84,
             *         85,
             *         86,
             *         87,
             *         88,
             *         89,
             *         90,
             *         91,
             *         92,
             *         93,
             *         94,
             *         95,
             *         96,
             *         97,
             *         98,
             *         99
             *       ],
             *       "fog": [
             *         false,
             *         true
             *       ],
             *       "income_per_property": [
             *         1000,
             *         1500,
             *         2000,
             *         2500,
             *         3000,
             *         3500,
             *         4000,
             *         4500,
             *         5000
             *       ],
             *       "weather": [
             *         "clear",
             *         "rain",
             *         "snow",
             *         "random"
             *       ]
             *     }
             */
            rule_options: components["schemas"]["RuleOptions"];
            /**
             * @default {
             *       "capture_limit": null,
             *       "co_powers": true,
             *       "contract_version": 1,
             *       "day_limit": 30,
             *       "fog": false,
             *       "income_per_property": 1000,
             *       "weather": "clear"
             *     }
             */
            rules: components["schemas"]["RuleConfiguration"];
            /**
             * Team Ids
             * @default [
             *       "a",
             *       "b",
             *       "c",
             *       "d"
             *     ]
             */
            team_ids: [
                "a",
                "b",
                "c",
                "d"
            ];
        };
        /** ConfigurationProfile */
        ConfigurationProfile: {
            /**
             * Availability
             * @default always_available
             * @enum {string}
             */
            availability: "always_available" | "save_dependent";
            /**
             * @default {
             *       "contract_version": 1,
             *       "map_id": "bean_island",
             *       "players": [
             *         {
             *           "co_id": "andy",
             *           "color": "red",
             *           "contract_version": 1,
             *           "control": "external",
             *           "slot": "slot_1",
             *           "team_id": "a"
             *         },
             *         {
             *           "co_id": "max",
             *           "color": "blue",
             *           "contract_version": 1,
             *           "control": "external",
             *           "slot": "slot_2",
             *           "team_id": "b"
             *         }
             *       ],
             *       "rules": {
             *         "capture_limit": null,
             *         "co_powers": true,
             *         "contract_version": 1,
             *         "day_limit": 30,
             *         "fog": false,
             *         "income_per_property": 1000,
             *         "weather": "clear"
             *       }
             *     }
             */
            configuration: components["schemas"]["MatchConfiguration"];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** @default classic */
            map_category: components["schemas"]["MapCategory"];
            /**
             * Profile Id
             * @default bean_island_v1
             */
            profile_id: string;
            /**
             * Requires Unlock
             * @default false
             */
            requires_unlock: boolean;
        };
        /** Coordinate */
        Coordinate: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /** CreateCheckpointRequest */
        CreateCheckpointRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** CreateMatchRequest */
        CreateMatchRequest: {
            /** @default null */
            configuration: components["schemas"]["MatchConfiguration"] | null;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /**
         * CursorStatus
         * @description Whether the observed map cursor can be reported for this frame.
         * @enum {string}
         */
        CursorStatus: "available" | "unavailable";
        /** DebugButtonsRequest */
        DebugButtonsRequest: {
            /** Buttons */
            buttons: ("a" | "b" | "select" | "start" | "up" | "down" | "left" | "right" | "l" | "r" | "neutral")[];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /** Frames */
            frames: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** DebugFramesRequest */
        DebugFramesRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /** Frames */
            frames: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** DebugMemoryReadRequest */
        DebugMemoryReadRequest: {
            /** Address */
            address: number;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /** Length */
            length: number;
        };
        /** DebugMemoryReadResponse */
        DebugMemoryReadResponse: {
            /** Address */
            address: number;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Data */
            data: string;
            /** Frame */
            frame: number;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            /** Revision */
            revision: number;
        };
        /** DebugMemoryWriteRequest */
        DebugMemoryWriteRequest: {
            /** Address */
            address: number;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Data */
            data: string;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** DebugResetRequest */
        DebugResetRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /**
         * DiveAction
         * @description Move a surfaced Sub and Dive.
         */
        DiveAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "dive";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Unit Id */
            unit_id: string;
        };
        /** EndTurnAction */
        EndTurnAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "end_turn";
        };
        /** ErrorBody */
        ErrorBody: {
            code: components["schemas"]["ErrorCode"];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Details */
            details?: {
                [key: string]: string | number | boolean | null;
            };
            /** Message */
            message: string;
            /**
             * Retryable
             * @default false
             */
            retryable: boolean;
        };
        /**
         * ErrorCode
         * @enum {string}
         */
        ErrorCode: "invalid_request" | "unsupported_feature" | "match_not_found" | "active_match_exists" | "match_closed" | "match_finished" | "slot_unavailable" | "invalid_credential" | "permission_denied" | "invalid_invitation" | "not_your_turn" | "stale_revision" | "request_id_conflict" | "command_not_found" | "command_capacity" | "server_shutting_down" | "observation_unavailable" | "action_rejected" | "timeout" | "rollback_failed" | "recovery_required" | "checkpoint_incompatible" | "checkpoint_corrupt" | "checkpoint_not_found" | "journal_corrupt" | "storage_unavailable" | "runtime_unavailable" | "internal_error";
        /** FeatureAvailability */
        FeatureAvailability: {
            /** Available */
            available: boolean;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Implemented */
            implemented: boolean;
            /** Name */
            name: string;
            /**
             * Unavailable Reason
             * @default null
             */
            unavailable_reason: string | null;
            /**
             * Verification
             * @enum {string}
             */
            verification: "unverified" | "synthetic" | "headless" | "windowed" | "headless_and_windowed";
        };
        /**
         * GameState
         * @description One coherent observation, with battle values gated by lifecycle and validation.
         */
        GameState: {
            battle: components["schemas"]["ObservedValue_BattleState_"];
            context: components["schemas"]["StateContext"];
            /** Frame */
            frame: number;
            /** Schema Version */
            schema_version: number;
            ui: components["schemas"]["UIStateObservation"];
            validation: components["schemas"]["BattleValidationReport"];
        };
        /**
         * GameplayCommandRequest
         * @description Match and player identity come from the route and authenticated principal.
         */
        GameplayCommandRequest: {
            /** Action */
            action: components["schemas"]["MoveWaitAction"] | components["schemas"]["MoveAttackAction"] | components["schemas"]["AttackAction"] | components["schemas"]["MoveCaptureAction"] | components["schemas"]["JoinAction"] | components["schemas"]["SupplyAction"] | components["schemas"]["DiveAction"] | components["schemas"]["RiseAction"] | components["schemas"]["SiloLaunchAction"] | components["schemas"]["LoadAction"] | components["schemas"]["UnloadAction"] | components["schemas"]["PurchaseAction"] | components["schemas"]["ActivateNormalPowerAction"] | components["schemas"]["ActivateSuperPowerAction"] | components["schemas"]["EndTurnAction"] | components["schemas"]["SurrenderAction"];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /**
         * IdentityStatus
         * @enum {string}
         */
        IdentityStatus: "available" | "unavailable";
        /** InvitationReference */
        InvitationReference: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Invitation Id
             * Format: uuid
             */
            invitation_id: string;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            player_slot: components["schemas"]["PlayerSlot"];
        };
        /** IssueInvitationRequest */
        "IssueInvitationRequest-Input": {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Expires In Seconds
             * @default 900
             */
            expires_in_seconds: number;
            /**
             * Invitation Token
             * Format: password
             */
            invitation_token: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** IssueInvitationRequest */
        "IssueInvitationRequest-Output": {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Expires In Seconds
             * @default 900
             */
            expires_in_seconds: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /**
         * JoinAction
         * @description Move a unit onto an adjacent allied unit of the same type and merge.
         */
        JoinAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "join";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Unit Id */
            unit_id: string;
        };
        /** JoinSlotRequest */
        "JoinSlotRequest-Input": {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Display Name */
            display_name: string;
            /**
             * Invitation Token
             * Format: password
             */
            invitation_token: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** JoinSlotRequest */
        "JoinSlotRequest-Output": {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Display Name */
            display_name: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** JoinSlotResponse */
        JoinSlotResponse: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            match: components["schemas"]["MatchSummary"];
            player_slot: components["schemas"]["PlayerSlot"];
        };
        /**
         * LifecycleAssessment
         * @description Conservative lifecycle result and script evidence from one frame.
         *
         *     ``matched_scripts`` lists signals used by the classifier;
         *     ``active_process_scripts`` preserves the nonzero script IDs in process-pool
         *     order, including IDs that did not match a known phase.
         */
        LifecycleAssessment: {
            /**
             * Active Process Scripts
             * @default []
             */
            active_process_scripts: number[];
            battle_decode_safety: components["schemas"]["BattleDecodeSafety"];
            engine: components["schemas"]["LifecycleEngine"];
            /**
             * Matched Scripts
             * @default []
             */
            matched_scripts: number[];
            phase: components["schemas"]["LifecyclePhase"];
        };
        /**
         * LifecycleEngine
         * @description The engine family selected by the observed callback pair.
         * @enum {string}
         */
        LifecycleEngine: "unknown" | "screen" | "battle" | "animation";
        /**
         * LifecyclePhase
         * @description Observed screen or engine phase, with ambiguous states kept explicit.
         * @enum {string}
         */
        LifecyclePhase: "unknown" | "startup" | "title" | "mode_select" | "versus_map_select" | "versus_setup" | "battle_transition" | "battle_combat" | "battle_power" | "battle_computer_turn" | "battle_player_turn" | "battle_engine_unresolved" | "result_sequence" | "victory_presentation" | "defeat_presentation" | "result_summary" | "save_progress_prompt";
        /**
         * LoadAction
         * @description Move one unit onto an allied transport's tile and load it.
         */
        LoadAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "load";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Transport Id */
            transport_id: string;
            /** Unit Id */
            unit_id: string;
        };
        /**
         * MCPCompatibility
         * @description SDK transport support, independent of implemented AW2 MCP features.
         */
        MCPCompatibility: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Endpoint
             * @default /mcp
             * @constant
             */
            endpoint: "/mcp";
            /**
             * Preferred Protocol Version
             * @default 2025-11-25
             */
            preferred_protocol_version: string;
            /** Sdk Version */
            sdk_version?: string;
            /**
             * Supported Protocol Versions
             * @default [
             *       "2024-11-05",
             *       "2025-03-26",
             *       "2025-06-18",
             *       "2025-11-25"
             *     ]
             */
            supported_protocol_versions: string[];
            /**
             * Transport
             * @default streamable_http
             * @constant
             */
            transport: "streamable_http";
        };
        /**
         * MapCategory
         * @enum {string}
         */
        MapCategory: "classic" | "versus" | "pre_deployed" | "three_player" | "four_player" | "war_room";
        /**
         * MapCursorObservation
         * @description Map cursor coordinates, distinct from menu selection and input readiness.
         */
        MapCursorObservation: {
            /** Frame */
            frame: number;
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            status: components["schemas"]["CursorStatus"];
            /**
             * X
             * @default null
             */
            x: number | null;
            /**
             * Y
             * @default null
             */
            y: number | null;
        };
        /** MapState */
        MapState: {
            /** Height */
            height: number;
            /** Tiles */
            tiles: components["schemas"]["TileState"][];
            /** Width */
            width: number;
        };
        /**
         * MatchConfiguration
         * @description Complete requested configuration; support validation is a separate step.
         */
        MatchConfiguration: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Map Id */
            map_id: string;
            /** Players */
            players: components["schemas"]["PlayerConfiguration"][];
            rules: components["schemas"]["RuleConfiguration"];
        };
        /**
         * MatchIdentityResponse
         * @description Authenticated caller's role in one match; contains no credential material.
         */
        MatchIdentityResponse: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            player_slot: components["schemas"]["PlayerSlot"] | null;
            /**
             * Role
             * @enum {string}
             */
            role: "operator" | "player";
        };
        /**
         * MatchLifecycle
         * @enum {string}
         */
        MatchLifecycle: "setup" | "playable" | "executing" | "finished" | "recovery_required" | "closed";
        /** MatchListResponse */
        MatchListResponse: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Matches */
            matches: components["schemas"]["MatchSummary"][];
        };
        /**
         * MatchObservation
         * @description A committed state with its match/revision and lifetime unit IDs.
         */
        MatchObservation: {
            action_readiness: components["schemas"]["ActionReadiness"];
            /** Action Readiness Reasons */
            action_readiness_reasons: string[];
            game_state: components["schemas"]["GameState"];
            /** Identity Reasons */
            identity_reasons: string[];
            identity_status: components["schemas"]["IdentityStatus"];
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            /** Revision */
            revision: number;
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            /** Unit Identities */
            unit_identities: components["schemas"]["UnitIdentityObservation"][];
        };
        /** MatchSummary */
        MatchSummary: {
            configuration: components["schemas"]["MatchConfiguration"];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            lifecycle: components["schemas"]["MatchLifecycle"];
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            /** Revision */
            revision: number;
            /** Slots */
            slots: components["schemas"]["PlayerSlotState"][];
        };
        /**
         * MenuFamily
         * @description Menu contexts supported by the current UI research subset.
         * @enum {string}
         */
        MenuFamily: "map_input" | "command" | "intel" | "options" | "unit_action" | "unit_movement" | "unit_action_choices" | "production_choices" | "confirmation" | "unit_targeting" | "unit_drop_targeting" | "silo_tutorial" | "silo_targeting" | "unresolved";
        /**
         * MenuItem
         * @description Choices resolved from the verified general battle selectors.
         * @enum {string}
         */
        MenuItem: "co" | "intel" | "power" | "super_power" | "options" | "save" | "end" | "status" | "unit" | "rules" | "delete" | "yield" | "music" | "visual_mode" | "exit_map" | "fire" | "capture" | "load" | "unload" | "wait" | "join" | "supply" | "dive" | "rise" | "launch" | "other_unit_action" | "yes" | "no";
        /**
         * MenuObservation
         * @description Recognized menu context and its current typed selection, when known.
         */
        MenuObservation: {
            /**
             * Actionable
             * @default null
             */
            actionable: boolean | null;
            /**
             * Confirmation Kind
             * @default null
             */
            confirmation_kind: string | null;
            family: components["schemas"]["MenuFamily"];
            /** Frame */
            frame: number;
            /**
             * Items
             * @default []
             */
            items: components["schemas"]["MenuItem"][];
            /**
             * Production Unit Types
             * @default []
             */
            production_unit_types: number[];
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            /** @default null */
            selected_item: components["schemas"]["MenuItem"] | null;
            /**
             * Selected Production Index
             * @default null
             */
            selected_production_index: number | null;
            /** @default null */
            selected_unit: components["schemas"]["SelectedUnitObservation"] | null;
            /** @default null */
            unrecognized: components["schemas"]["UnrecognizedUIState"] | null;
        };
        /** MoveAttackAction */
        MoveAttackAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "move_attack";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            target: components["schemas"]["Coordinate"];
            /** Unit Id */
            unit_id: string;
        };
        /** MoveCaptureAction */
        MoveCaptureAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "move_capture";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Unit Id */
            unit_id: string;
        };
        /** MoveWaitAction */
        MoveWaitAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "move_wait";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Unit Id */
            unit_id: string;
        };
        /** ObservationResponse */
        ObservationResponse: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            observation: components["schemas"]["MatchObservation"];
        };
        /**
         * ObservedValue
         * @description A value with explicit availability; zero and an empty roster are valid values.
         */
        ObservedValue_BattleState_: {
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            status: components["schemas"]["ValueStatus"];
            value: components["schemas"]["BattleState"] | null;
        };
        /**
         * ObservedValue
         * @description A value with explicit availability; zero and an empty roster are valid values.
         */
        ObservedValue_Weather_: {
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            status: components["schemas"]["ValueStatus"];
            value: components["schemas"]["Weather"] | null;
        };
        /**
         * ObservedValue
         * @description A value with explicit availability; zero and an empty roster are valid values.
         */
        ObservedValue_bool_: {
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            status: components["schemas"]["ValueStatus"];
            /** Value */
            value: boolean | null;
        };
        /**
         * ObservedValue
         * @description A value with explicit availability; zero and an empty roster are valid values.
         */
        ObservedValue_int_: {
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            status: components["schemas"]["ValueStatus"];
            /** Value */
            value: number | null;
        };
        /**
         * OperatorPrincipal
         * @description Trusted server-created identity; never construct from gameplay tool arguments.
         */
        OperatorPrincipal: {
            /** Authorization Generation */
            authorization_generation: number;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Kind
             * @default operator
             * @constant
             */
            kind: "operator";
        };
        /** PlayerConfiguration */
        PlayerConfiguration: {
            /** Co Id */
            co_id: string;
            /**
             * Color
             * @enum {string}
             */
            color: "red" | "blue" | "green" | "yellow" | "black";
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Control
             * @enum {string}
             */
            control: "external" | "computer";
            /**
             * Slot
             * @enum {string}
             */
            slot: "slot_1" | "slot_2" | "slot_3" | "slot_4";
            /**
             * Team Id
             * @enum {string}
             */
            team_id: "a" | "b" | "c" | "d";
        };
        /** PlayerPrincipal */
        PlayerPrincipal: {
            /** Authorization Generation */
            authorization_generation: number;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Kind
             * @default player
             * @constant
             */
            kind: "player";
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            player_slot: components["schemas"]["PlayerSlot"];
        };
        /**
         * PlayerSlot
         * @enum {string}
         */
        PlayerSlot: "slot_1" | "slot_2" | "slot_3" | "slot_4";
        /** PlayerSlotState */
        PlayerSlotState: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Display Name
             * @default null
             */
            display_name: string | null;
            slot: components["schemas"]["PlayerSlot"];
            status: components["schemas"]["SlotStatus"];
        };
        /** PlayerState */
        PlayerState: {
            /** Active Power */
            active_power: number;
            /** Co Id */
            co_id: number;
            /** Control Type */
            control_type: number;
            /** Funds */
            funds: number;
            power_meter: components["schemas"]["ObservedValue_int_"];
            power_use_counter: components["schemas"]["ObservedValue_int_"];
            /** Slot */
            slot: number;
            /** Team Id */
            team_id: number;
        };
        /**
         * ProductionFacilityCapabilities
         * @description Production choices available at one observed facility terrain type.
         */
        ProductionFacilityCapabilities: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Name */
            name: string;
            /** Terrain Class */
            terrain_class: number;
            /** Unit Types */
            unit_types: string[];
        };
        /**
         * PropertyState
         * @description A property or silo feature; capture progress belongs to its capturing unit.
         */
        PropertyState: {
            /** Owner Slot */
            owner_slot: number;
            /** Terrain Class */
            terrain_class: number;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /** PurchaseAction */
        PurchaseAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "purchase";
            property: components["schemas"]["Coordinate"];
            /** Unit Type */
            unit_type: string;
        };
        /** ReadinessResponse */
        ReadinessResponse: {
            bridge: components["schemas"]["ReadinessState"];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            emulator: components["schemas"]["ReadinessState"];
            /**
             * Http
             * @default ready
             * @constant
             */
            http: "ready";
            /**
             * Match Id
             * @default null
             */
            match_id: string | null;
            /** @default null */
            match_lifecycle: components["schemas"]["MatchLifecycle"] | null;
            /**
             * Match Ready
             * @default false
             */
            match_ready: boolean;
            queue: components["schemas"]["ReadinessState"];
            /**
             * Recovery
             * @enum {string}
             */
            recovery: "not_required" | "required" | "in_progress";
        };
        /**
         * ReadinessState
         * @enum {string}
         */
        ReadinessState: "ready" | "unavailable" | "not_configured";
        /** Request */
        Request: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** RestoreCheckpointRequest */
        RestoreCheckpointRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** RevisionRequest */
        RevisionRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /** RevokeSlotRequest */
        RevokeSlotRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /**
         * RiseAction
         * @description Move a submerged Sub and Rise.
         */
        RiseAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "rise";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Unit Id */
            unit_id: string;
        };
        /**
         * RomProfile
         * @description A verified ROM identity and the versions used to interpret its memory.
         */
        RomProfile: {
            /** Decoder Version */
            decoder_version: string;
            /** Game Code */
            game_code: string;
            /** Maker Code */
            maker_code: string;
            /** Memory Layout Version */
            memory_layout_version: string;
            /** Name */
            name: string;
            /** Revision */
            revision: number;
            /** Sha256 */
            sha256: string;
            /** Title */
            title: string;
        };
        /** RuleConfiguration */
        RuleConfiguration: {
            /** Capture Limit */
            capture_limit: number | null;
            /** Co Powers */
            co_powers: boolean;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Day Limit */
            day_limit: number | null;
            /** Fog */
            fog: boolean;
            /** Income Per Property */
            income_per_property: number;
            /**
             * Weather
             * @enum {string}
             */
            weather: "clear" | "rain" | "snow" | "random";
        };
        /**
         * RuleOptions
         * @description Independently selectable rule values accepted by the verified setup flow.
         */
        RuleOptions: {
            /**
             * Capture Limit
             * @default [
             *       null,
             *       12,
             *       13,
             *       14,
             *       15,
             *       16,
             *       17,
             *       18,
             *       19,
             *       20,
             *       21,
             *       22,
             *       23,
             *       24,
             *       25,
             *       26,
             *       27
             *     ]
             */
            capture_limit: (number | null)[];
            /**
             * Co Powers
             * @default [
             *       true,
             *       false
             *     ]
             */
            co_powers: boolean[];
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Day Limit
             * @default [
             *       null,
             *       5,
             *       6,
             *       7,
             *       8,
             *       9,
             *       10,
             *       11,
             *       12,
             *       13,
             *       14,
             *       15,
             *       16,
             *       17,
             *       18,
             *       19,
             *       20,
             *       21,
             *       22,
             *       23,
             *       24,
             *       25,
             *       26,
             *       27,
             *       28,
             *       29,
             *       30,
             *       31,
             *       32,
             *       33,
             *       34,
             *       35,
             *       36,
             *       37,
             *       38,
             *       39,
             *       40,
             *       41,
             *       42,
             *       43,
             *       44,
             *       45,
             *       46,
             *       47,
             *       48,
             *       49,
             *       50,
             *       51,
             *       52,
             *       53,
             *       54,
             *       55,
             *       56,
             *       57,
             *       58,
             *       59,
             *       60,
             *       61,
             *       62,
             *       63,
             *       64,
             *       65,
             *       66,
             *       67,
             *       68,
             *       69,
             *       70,
             *       71,
             *       72,
             *       73,
             *       74,
             *       75,
             *       76,
             *       77,
             *       78,
             *       79,
             *       80,
             *       81,
             *       82,
             *       83,
             *       84,
             *       85,
             *       86,
             *       87,
             *       88,
             *       89,
             *       90,
             *       91,
             *       92,
             *       93,
             *       94,
             *       95,
             *       96,
             *       97,
             *       98,
             *       99
             *     ]
             */
            day_limit: (number | null)[];
            /**
             * Fog
             * @default [
             *       false,
             *       true
             *     ]
             */
            fog: boolean[];
            /**
             * Income Per Property
             * @default [
             *       1000,
             *       1500,
             *       2000,
             *       2500,
             *       3000,
             *       3500,
             *       4000,
             *       4500,
             *       5000
             *     ]
             */
            income_per_property: number[];
            /**
             * Weather
             * @default [
             *       "clear",
             *       "rain",
             *       "snow",
             *       "random"
             *     ]
             */
            weather: ("clear" | "rain" | "snow" | "random")[];
        };
        /**
         * SelectedUnitObservation
         * @description A unit record resolved in a verified unit-action menu context.
         */
        SelectedUnitObservation: {
            /** Army Slot */
            army_slot: number;
            /** Record Address */
            record_address: number;
            /**
             * Submerged
             * @default false
             */
            submerged: boolean;
            /** Unit Slot */
            unit_slot: number;
            /** Unit Type */
            unit_type: number;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /**
         * SiloLaunchAction
         * @description Move an Infantry/Mech onto an unused silo and launch at a map coordinate.
         */
        SiloLaunchAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "silo_launch";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            target: components["schemas"]["Coordinate"];
            /** Unit Id */
            unit_id: string;
        };
        /**
         * SlotAuthorization
         * @description Public authorization metadata; no verifiers or invitation secrets.
         */
        SlotAuthorization: {
            /** Authorization Generation */
            authorization_generation: number;
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * Display Name
             * @default null
             */
            display_name: string | null;
            /**
             * Match Id
             * Format: uuid
             */
            match_id: string;
            player_slot: components["schemas"]["PlayerSlot"];
            status: components["schemas"]["SlotStatus"];
        };
        /**
         * SlotStatus
         * @enum {string}
         */
        SlotStatus: "open" | "joined" | "revoked";
        /** StartMatchRequest */
        StartMatchRequest: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
        };
        /**
         * StateContext
         * @description ROM and decoder identity required to interpret this state document.
         */
        StateContext: {
            rom_profile: components["schemas"]["RomProfile"];
        };
        /** StateResponse */
        StateResponse: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            observation: components["schemas"]["MatchObservation"] | null;
            /** Settled */
            settled: boolean;
            summary: components["schemas"]["MatchSummary"];
        };
        /** StructureValidation */
        StructureValidation: {
            /**
             * Count
             * @default null
             */
            count: number | null;
            /**
             * Reasons
             * @default []
             */
            reasons: string[];
            status: components["schemas"]["ValidationStatus"];
        };
        /**
         * SupplyAction
         * @description Move an APC and supply every adjacent allied unit.
         */
        SupplyAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "supply";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Unit Id */
            unit_id: string;
        };
        /** SurrenderAction */
        SurrenderAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "surrender";
        };
        /** TileState */
        TileState: {
            /** Graphical Tile Id */
            graphical_tile_id: number;
            /** Owner Slot */
            owner_slot: number;
            /** Terrain Class */
            terrain_class: number;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /**
         * UIStateObservation
         * @description Cursor and menu observations made from the same emulator frame.
         */
        UIStateObservation: {
            /** Frame */
            frame: number;
            map_cursor: components["schemas"]["MapCursorObservation"];
            menu: components["schemas"]["MenuObservation"];
        };
        /**
         * UnitIdentityObservation
         * @description Public lifetime identity keyed by the decoder's reusable unit reference.
         */
        UnitIdentityObservation: {
            /** Generation */
            generation: number;
            /** Identity Id */
            identity_id: string;
            /** Reference */
            reference: number;
        };
        /**
         * UnitState
         * @description Verified record fields; reference is a reusable slot, not a lifetime ID.
         *
         *     Embarked units retain record coordinates which may differ from their transport.
         *     Unassigned status/fuel bits and HUD health rounding are intentionally omitted.
         */
        UnitState: {
            /** Ammo */
            ammo: number;
            /** Army Slot */
            army_slot: number;
            /** Capture Points */
            capture_points: number;
            /** Cargo References */
            cargo_references: number[];
            /** Embarked */
            embarked: boolean;
            /** Fuel */
            fuel: number;
            /** Internal Health */
            internal_health: number;
            /** Reference */
            reference: number;
            /**
             * Submerged
             * @default false
             */
            submerged: boolean;
            /** Unit Slot */
            unit_slot: number;
            /** Unit Type */
            unit_type: number;
            /** Used This Turn */
            used_this_turn: boolean;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /**
         * UnloadAction
         * @description Move a carrier, then unload one or more named cargo units.
         */
        UnloadAction: {
            /**
             * Contract Version
             * @default 1
             * @constant
             */
            contract_version: 1;
            /** Drops */
            drops: components["schemas"]["CargoDrop"][];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "unload";
            /** Path */
            path: components["schemas"]["Coordinate"][];
            /** Transport Id */
            transport_id: string;
        };
        /**
         * UnrecognizedUIState
         * @description Raw classification evidence retained when no supported UI family fits.
         */
        UnrecognizedUIState: {
            controller: components["schemas"]["BattleControlObservation"];
            /** Frame */
            frame: number;
            lifecycle: components["schemas"]["LifecycleAssessment"];
            /** Reason */
            reason: string;
            /** Selector Object */
            selector_object: number;
            /** Selector Table */
            selector_table: number;
        };
        /**
         * ValidationStatus
         * @enum {string}
         */
        ValidationStatus: "valid" | "invalid" | "unknown";
        /**
         * ValueStatus
         * @enum {string}
         */
        ValueStatus: "available" | "unavailable" | "unknown";
        /**
         * Weather
         * @enum {string}
         */
        Weather: "clear" | "snow" | "rain";
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export type operations = Record<string, never>;
