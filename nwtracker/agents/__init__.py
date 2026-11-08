"""One independent extraction module per agent."""
from .avison_young import AvisonYoung
from .b8 import B8RealEstate
from .bc_real_estate import BCRealEstate
from .cbre import CBRE
from .colliers import Colliers
from .cpp import CPP
from .cushman import Cushman
from .davies_harrison import DaviesHarrison
from .fisher_german import FisherGerman
from .dtre import DTRE
from .jll import JLL
from .knight_frank import KnightFrank
from .legat_owen import LegatOwen
from .lm6 import LM6
from .lsh import LSH
from .savills import Savills
from .taylor_weaver import TaylorWeaver
from .williams_sillitoe import WilliamsSillitoe

AGENTS = {
    "jll": JLL,
    "cbre": CBRE,
    "cushman": Cushman,
    "avisonyoung": AvisonYoung,
    "willsill": WilliamsSillitoe,
    "b8": B8RealEstate,
    "dtre": DTRE,
    "cpp": CPP,
    "bc": BCRealEstate,
    "daviesharrison": DaviesHarrison,
    "legatowen": LegatOwen,
    "lsh": LSH,
    "savills": Savills,
    "knightfrank": KnightFrank,
    "colliers": Colliers,
    "taylorweaver": TaylorWeaver,
    "lm6": LM6,
    "fishergerman": FisherGerman,
}
