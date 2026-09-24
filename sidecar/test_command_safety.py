"""Offline mirrors of host command legality (catalog == apply gate)."""
import unittest

_PLOT_TARGET_MISSIONS = frozenset([
    "MISSION_MOVE_TO", "MISSION_ROUTE_TO", "MISSION_MOVE_TO_UNIT",
    "MISSION_ATTACK", "MISSION_PILLAGE", "MISSION_BOMBARD",
    "MISSION_AIRLIFT", "MISSION_RECON", "MISSION_PARADROP",
    "MISSION_STRIKE", "MISSION_NUKE",
])
_POPUP_MISSIONS = frozenset(["MISSION_ESPIONAGE", "MISSION_LEAD"])
_DATA_FREE_POSTURE_MISSIONS = frozenset([
    "MISSION_SKIP", "MISSION_SLEEP", "MISSION_FORTIFY", "MISSION_HEAL", "MISSION_SENTRY",
])


def catalog_allows_generic_probe(mission_id: str) -> bool:
    return mission_id in _DATA_FREE_POSTURE_MISSIONS


class FakeCity:
    def __init__(self, can_train=None, can_construct=None, can_conscript=False,
                 can_hurry=None, can_raze=False, liberate=-1):
        self.can_train = set(can_train or [])
        self.can_construct = set(can_construct or [])
        self.can_conscript = can_conscript
        self.can_hurry = set(can_hurry or [])
        self.can_raze = can_raze
        self.liberate = liberate

    def canTrain(self, item, *_args):
        return item in self.can_train

    def canConstruct(self, item, *_args):
        return item in self.can_construct

    def canCreate(self, item, *_args):
        return False

    def canMaintain(self, item, *_args):
        return False

    def canConscript(self):
        return self.can_conscript

    def canHurry(self, hurry, *_args):
        return hurry in self.can_hurry

    def getLiberationPlayer(self):
        return self.liberate


class FakePlayer:
    def __init__(self, research=None, civics=None, convert=None, flexible=None,
                 cities=None, num_cities=1, team=0):
        self.research = set(research or [])
        self.civics = set(civics or [])
        self.convert = set(convert or [])
        self.flexible = set(flexible or [])
        self.cities = cities or {}
        self.num_cities = num_cities
        self.team = team
        self.current_civics = {}

    def canResearch(self, tech):
        return tech in self.research

    def canDoCivics(self, civic):
        return civic in self.civics

    def getCivics(self, option):
        return self.current_civics.get(option, -1)

    def canConvert(self, religion):
        return religion in self.convert

    def isCommerceFlexible(self, commerce):
        return commerce in self.flexible

    def canRaze(self, city):
        return city.can_raze

    def getNumCities(self):
        return self.num_cities

    def getTeam(self):
        return self.team

    def getCity(self, index):
        return self.cities.get(index)


def legal_research(player: FakePlayer, tech_index: int) -> bool:
    return player.canResearch(tech_index)


def legal_civic(player: FakePlayer, civic_index: int, option_index: int) -> bool:
    if not player.canDoCivics(civic_index):
        return False
    if player.getCivics(option_index) == civic_index:
        return False
    return True


def legal_production(city: FakeCity, order: str, item: int) -> bool:
    if order == "TRAIN":
        return city.canTrain(item)
    if order == "CONSTRUCT":
        return city.canConstruct(item)
    return False


def legal_religion(player: FakePlayer, religion: int) -> bool:
    return player.canConvert(religion)


def catalog_filter(actions, is_legal):
    """Mirror: only advertise actions apply would accept."""
    return [action for action in actions if is_legal(action)]


class CommandSafetyTests(unittest.TestCase):
    def test_generic_probe_allowlist_excludes_route_and_popup_missions(self):
        self.assertTrue(catalog_allows_generic_probe("MISSION_SLEEP"))
        self.assertFalse(catalog_allows_generic_probe("MISSION_ROUTE_TO"))
        self.assertFalse(catalog_allows_generic_probe("MISSION_ESPIONAGE"))
        self.assertFalse(catalog_allows_generic_probe("MISSION_LEAD"))

    def test_research_catalog_only_can_research(self):
        player = FakePlayer(research={2, 5})
        offered = [i for i in range(8) if legal_research(player, i)]
        self.assertEqual([2, 5], offered)

    def test_civic_catalog_skips_current_and_illegal(self):
        player = FakePlayer(civics={1, 2, 3})
        player.current_civics[0] = 1
        offered = [i for i in (1, 2, 3) if legal_civic(player, i, 0)]
        self.assertEqual([2, 3], offered)

    def test_production_catalog_uses_city_can_apis(self):
        city = FakeCity(can_train={10}, can_construct={20})
        self.assertTrue(legal_production(city, "TRAIN", 10))
        self.assertFalse(legal_production(city, "TRAIN", 11))
        self.assertTrue(legal_production(city, "CONSTRUCT", 20))

    def test_religion_catalog_uses_can_convert(self):
        player = FakePlayer(convert={1})
        self.assertTrue(legal_religion(player, 1))
        self.assertFalse(legal_religion(player, 0))

    def test_catalog_filter_drops_apply_illegal(self):
        actions = [
            {"kind": "set_research", "tech_id": "TECH_A"},
            {"kind": "set_research", "tech_id": "TECH_B"},
        ]
        legal = {"TECH_A"}
        filtered = catalog_filter(actions, lambda a: a["tech_id"] in legal)
        self.assertEqual([actions[0]], filtered)

    def test_plot_missions_never_in_generic_probe(self):
        for mission in _PLOT_TARGET_MISSIONS | _POPUP_MISSIONS:
            self.assertFalse(catalog_allows_generic_probe(mission))


if __name__ == "__main__":
    unittest.main()
