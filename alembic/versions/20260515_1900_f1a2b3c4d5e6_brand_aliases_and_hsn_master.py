"""Create brand_aliases table and populate hsn_master with CBIC 2024-25 data.

Revision ID: f1a2b3c4d5e6
Revises: e9f1a2b3c4d5
Create Date: 2026-05-15 19:00:00

Changes (ADDITIVE ONLY — no DELETE, no TRUNCATE):
  1. Create brand_aliases table (FMCG brand → HSN → GST mapping)
  2. Create indexes for brand_aliases (exact + trigram)
  3. Create keyword_category_map table (for Tier-4 keyword search)
  4. Create pending_review table (for Tier-6 manual review)
  5. Create search_cache table (cross-tier result cache)
  6. Populate hsn_master with CBIC HSN 2024-25 records
  7. Populate brand_aliases with 500+ top Indian FMCG brands
  8. Populate keyword_category_map

Sources:
  - CBIC HSN Master 2024-25
  - GST Council Notifications up to March 2025
  - CBIC Notification 1/2017-CT(Rate) and amendments
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e9f1a2b3c4d5"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# HSN Master data — CBIC 2024-25 — INSERT ON CONFLICT DO UPDATE
# (chapter, hsn_code, description, gst_rate, cess_applicable, category)
# ---------------------------------------------------------------------------
_HSN_MASTER_ROWS = [
    # ── Chapter 01 — Live Animals ──────────────────────────────────────────
    (1, "01011000", "Pure-bred breeding horses", 0.0, False, "Live Animals"),
    (1, "01019010", "Horses other than breeding", 0.0, False, "Live Animals"),
    (1, "01022100", "Pure-bred breeding cattle", 0.0, False, "Live Animals"),
    (1, "01029010", "Other live cattle", 0.0, False, "Live Animals"),
    (1, "01031000", "Pure-bred breeding swine", 0.0, False, "Live Animals"),
    (1, "01061100", "Primates", 0.0, False, "Live Animals"),
    (1, "01069000", "Other live animals", 0.0, False, "Live Animals"),
    # ── Chapter 02 — Meat ──────────────────────────────────────────────────
    (2, "02011000", "Carcases/half-carcases of bovine animals, fresh/chilled", 0.0, False, "Meat"),
    (2, "02021000", "Carcases/half-carcases of bovine animals, frozen", 0.0, False, "Meat"),
    (2, "02071100", "Chickens not cut, fresh/chilled", 5.0, False, "Meat"),
    (2, "02071200", "Chickens not cut, frozen", 5.0, False, "Meat"),
    (2, "02089000", "Other meat, frozen", 12.0, False, "Meat"),
    # ── Chapter 03 — Fish ──────────────────────────────────────────────────
    (3, "03011100", "Ornamental freshwater fish, live", 0.0, False, "Fish & Seafood"),
    (3, "03021100", "Trout, fresh/chilled", 5.0, False, "Fish & Seafood"),
    (3, "03031100", "Frozen salmon", 5.0, False, "Fish & Seafood"),
    (3, "03061100", "Rock lobster, frozen", 5.0, False, "Fish & Seafood"),
    (3, "03061400", "Crabs, frozen", 5.0, False, "Fish & Seafood"),
    (3, "03074300", "Cuttlefish", 5.0, False, "Fish & Seafood"),
    # ── Chapter 04 — Dairy, Eggs, Honey ───────────────────────────────────
    (4, "04011000", "Milk, not concentrated, <1% fat", 0.0, False, "Dairy"),
    (4, "04012000", "Milk, not concentrated, >1% <6% fat", 0.0, False, "Dairy"),
    (4, "04021000", "Milk powder <1.5% fat", 5.0, False, "Dairy"),
    (4, "04022100", "Milk powder >1.5% fat, unsweetened", 5.0, False, "Dairy"),
    (4, "04029900", "Other milk/cream preparations", 5.0, False, "Dairy"),
    (4, "04031000", "Yogurt/curd", 5.0, False, "Dairy"),
    (4, "04039000", "Other buttermilk/kephir", 5.0, False, "Dairy"),
    (4, "04041000", "Whey", 5.0, False, "Dairy"),
    (4, "04051000", "Butter", 12.0, False, "Dairy"),
    (4, "04052000", "Dairy spreads", 12.0, False, "Dairy"),
    (4, "04059000", "Other dairy fats", 12.0, False, "Dairy"),
    (4, "04061000", "Fresh cheese (unripened)", 12.0, False, "Dairy"),
    (4, "04069000", "Other cheese", 12.0, False, "Dairy"),
    (4, "04070000", "Eggs in shell, fresh/preserved/cooked", 0.0, False, "Dairy"),
    (4, "04090000", "Natural honey", 3.0, False, "Dairy"),
    # ── Chapter 07 — Vegetables ────────────────────────────────────────────
    (7, "07011000", "Seed potatoes, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07019000", "Other potatoes, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07020000", "Tomatoes, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07031000", "Onions/shallots, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07032000", "Garlic, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07041000", "Cauliflower, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07051100", "Cabbage lettuce (head), fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07061000", "Carrots and turnips", 0.0, False, "Vegetables"),
    (7, "07092000", "Asparagus, fresh/chilled", 0.0, False, "Vegetables"),
    (7, "07096000", "Fruits of capsicum/pimento", 0.0, False, "Vegetables"),
    (7, "07112000", "Olives, provisionally preserved", 0.0, False, "Vegetables"),
    (7, "07122000", "Dried onions", 5.0, False, "Vegetables"),
    (7, "07129000", "Other dried vegetables", 5.0, False, "Vegetables"),
    # ── Chapter 08 — Fruits & Nuts ─────────────────────────────────────────
    (8, "08011100", "Desiccated coconut", 0.0, False, "Fruits & Nuts"),
    (8, "08011200", "Coconuts in shell", 0.0, False, "Fruits & Nuts"),
    (8, "08019100", "Cashew nuts in shell", 5.0, False, "Fruits & Nuts"),
    (8, "08019200", "Cashew nuts shelled", 5.0, False, "Fruits & Nuts"),
    (8, "08021100", "Almonds in shell", 0.0, False, "Fruits & Nuts"),
    (8, "08021200", "Almonds shelled", 0.0, False, "Fruits & Nuts"),
    (8, "08023100", "Walnuts in shell", 5.0, False, "Fruits & Nuts"),
    (8, "08031000", "Plantains/bananas, fresh/dried", 0.0, False, "Fruits & Nuts"),
    (8, "08043000", "Pineapples, fresh/dried", 0.0, False, "Fruits & Nuts"),
    (8, "08045000", "Guavas, mangoes and mangosteens", 0.0, False, "Fruits & Nuts"),
    (8, "08051000", "Oranges, fresh/dried", 0.0, False, "Fruits & Nuts"),
    (8, "08052000", "Mandarins/tangerines/clementines", 0.0, False, "Fruits & Nuts"),
    (8, "08062000", "Dried grapes/raisins", 0.0, False, "Fruits & Nuts"),
    (8, "08071100", "Watermelons, fresh", 0.0, False, "Fruits & Nuts"),
    (8, "08081000", "Apples, fresh", 0.0, False, "Fruits & Nuts"),
    (8, "08082000", "Pears and quinces, fresh", 0.0, False, "Fruits & Nuts"),
    (8, "08091000", "Apricots, fresh", 0.0, False, "Fruits & Nuts"),
    (8, "08101000", "Strawberries, fresh", 0.0, False, "Fruits & Nuts"),
    # ── Chapter 09 — Coffee, Tea, Spices ──────────────────────────────────
    (9, "09011100", "Coffee, not roasted, not decaffeinated", 0.0, False, "Coffee Tea Spices"),
    (9, "09011200", "Coffee, not roasted, decaffeinated", 0.0, False, "Coffee Tea Spices"),
    (9, "09021000", "Green tea (not fermented)", 5.0, False, "Coffee Tea Spices"),
    (9, "09022000", "Other green tea", 5.0, False, "Coffee Tea Spices"),
    (9, "09023000", "Black tea (fermented)", 5.0, False, "Coffee Tea Spices"),
    (9, "09024000", "Other partly/wholly fermented tea", 5.0, False, "Coffee Tea Spices"),
    (9, "09031000", "Mate", 5.0, False, "Coffee Tea Spices"),
    (9, "09041100", "Pepper (not crushed/ground)", 5.0, False, "Coffee Tea Spices"),
    (9, "09041200", "Pepper, crushed/ground", 5.0, False, "Coffee Tea Spices"),
    (9, "09042100", "Dried chilli (not crushed)", 5.0, False, "Coffee Tea Spices"),
    (9, "09042200", "Dried chilli, crushed/ground", 5.0, False, "Coffee Tea Spices"),
    (9, "09061000", "Cinnamon bark, whole", 0.0, False, "Coffee Tea Spices"),
    (9, "09071000", "Cloves (whole)", 0.0, False, "Coffee Tea Spices"),
    (9, "09081100", "Nutmeg", 0.0, False, "Coffee Tea Spices"),
    (9, "09101100", "Ginger, not crushed/ground", 5.0, False, "Coffee Tea Spices"),
    (9, "09101200", "Ginger, crushed/ground", 5.0, False, "Coffee Tea Spices"),
    (9, "09103000", "Turmeric (curcuma)", 5.0, False, "Coffee Tea Spices"),
    (9, "09109910", "Mixed spice blends (masala)", 5.0, False, "Coffee Tea Spices"),
    # ── Chapter 10 — Cereals ───────────────────────────────────────────────
    (10, "10011000", "Durum wheat", 0.0, False, "Cereals"),
    (10, "10019000", "Other wheat/meslin", 0.0, False, "Cereals"),
    (10, "10051000", "Seed maize (corn)", 0.0, False, "Cereals"),
    (10, "10059000", "Other maize (corn)", 0.0, False, "Cereals"),
    (10, "10061000", "Rice in husk (paddy/rough)", 0.0, False, "Cereals"),
    (10, "10062000", "Husked (brown) rice", 0.0, False, "Cereals"),
    (10, "10063000", "Semi-milled or wholly milled rice", 5.0, False, "Cereals"),
    (10, "10064000", "Broken rice", 0.0, False, "Cereals"),
    (10, "10070000", "Grain sorghum", 0.0, False, "Cereals"),
    (10, "10081000", "Buckwheat", 0.0, False, "Cereals"),
    (10, "10082000", "Millet", 0.0, False, "Cereals"),
    # ── Chapter 11 — Milling Products ──────────────────────────────────────
    (11, "11010000", "Wheat or meslin flour", 5.0, False, "Milling Products"),
    (11, "11022000", "Maize (corn) flour", 5.0, False, "Milling Products"),
    (11, "11031100", "Groats and meal of wheat", 5.0, False, "Milling Products"),
    (11, "11041200", "Rolled/flaked oats", 5.0, False, "Milling Products"),
    (11, "11061000", "Flour/powder of dried leguminous veg", 5.0, False, "Milling Products"),
    (11, "11071000", "Malt, not roasted", 5.0, False, "Milling Products"),
    (11, "11072000", "Malt, roasted", 5.0, False, "Milling Products"),
    (11, "11081100", "Wheat starch", 12.0, False, "Milling Products"),
    (11, "11081300", "Potato starch", 12.0, False, "Milling Products"),
    # ── Chapter 15 — Fats & Oils ───────────────────────────────────────────
    (15, "15071000", "Crude soya-bean oil", 5.0, False, "Fats & Oils"),
    (15, "15079000", "Other soya-bean oil", 5.0, False, "Fats & Oils"),
    (15, "15081000", "Crude groundnut oil", 5.0, False, "Fats & Oils"),
    (15, "15089000", "Other groundnut oil", 5.0, False, "Fats & Oils"),
    (15, "15091000", "Virgin olive oil", 5.0, False, "Fats & Oils"),
    (15, "15111000", "Crude palm oil", 5.0, False, "Fats & Oils"),
    (15, "15119000", "Other palm oil (refined)", 5.0, False, "Fats & Oils"),
    (15, "15121100", "Crude sunflower-seed/safflower oil", 5.0, False, "Fats & Oils"),
    (15, "15121910", "Refined sunflower-seed/safflower oil", 5.0, False, "Fats & Oils"),
    (15, "15131100", "Crude coconut oil", 5.0, False, "Fats & Oils"),
    (15, "15132900", "Other coconut oil (refined)", 5.0, False, "Fats & Oils"),
    (15, "15141100", "Low erucic acid rape/colza oil, crude", 5.0, False, "Fats & Oils"),
    (15, "15171000", "Margarine", 12.0, False, "Fats & Oils"),
    (15, "15179010", "Refined edible blended oil (Fortune/Saffola)", 5.0, False, "Fats & Oils"),
    (15, "15200000", "Glycerol, crude", 18.0, False, "Fats & Oils"),
    (15, "15221000", "Degras; residues from treatment of fatty substances", 18.0, False, "Fats & Oils"),
    # ── Chapter 16 — Prepared Meat/Fish ────────────────────────────────────
    (16, "16010000", "Sausages and similar products", 12.0, False, "Prepared Food"),
    (16, "16021000", "Homogenised preparations of meat", 12.0, False, "Prepared Food"),
    (16, "16041100", "Prepared/preserved salmon", 12.0, False, "Prepared Food"),
    (16, "16054000", "Crustacean preparations", 12.0, False, "Prepared Food"),
    # ── Chapter 17 — Sugars & Confectionery ───────────────────────────────
    (17, "17011200", "Beet sugar, raw", 5.0, False, "Sugar & Confectionery"),
    (17, "17019100", "Refined cane/beet sugar", 5.0, False, "Sugar & Confectionery"),
    (17, "17022000", "Maple sugar and maple syrup", 5.0, False, "Sugar & Confectionery"),
    (17, "17041000", "Chewing gum", 18.0, False, "Sugar & Confectionery"),
    (17, "17049000", "Other sugar confectionery", 18.0, False, "Sugar & Confectionery"),
    # ── Chapter 18 — Cocoa & Chocolate ────────────────────────────────────
    (18, "18010000", "Cocoa beans, whole/broken, raw/roasted", 0.0, False, "Cocoa & Chocolate"),
    (18, "18040000", "Cocoa butter, fat and oil", 18.0, False, "Cocoa & Chocolate"),
    (18, "18050000", "Cocoa powder, not sweetened", 18.0, False, "Cocoa & Chocolate"),
    (18, "18061000", "Cocoa powder with sugar", 18.0, False, "Cocoa & Chocolate"),
    (18, "18062000", "Chocolate and cocoa food preparations >2kg", 18.0, False, "Cocoa & Chocolate"),
    (18, "18063100", "Filled chocolate", 18.0, False, "Cocoa & Chocolate"),
    (18, "18063200", "Chocolate tablets/bars (not filled) — KitKat, Dairy Milk, 5Star", 28.0, False, "Cocoa & Chocolate"),
    (18, "18069000", "Other chocolate preparations (Bournvita base)", 18.0, False, "Cocoa & Chocolate"),
    # ── Chapter 19 — Cereal Preparations ─────────────────────────────────
    (19, "19011002", "Infant preparations, malt extract — retail, for infants", 18.0, False, "Cereal Preparations"),
    (19, "19011010", "Preparations suitable for infants/young children (Pediasure, Similac)", 18.0, False, "Cereal Preparations"),
    (19, "19011090", "Malt extract; food preparations of flour/meal/starch/malt — other", 18.0, False, "Cereal Preparations"),
    (19, "19012000", "Mixes/doughs for bakers wares", 18.0, False, "Cereal Preparations"),
    (19, "19019090", "Malted milk food preparations — malt-based health drinks (Horlicks, Boost, Bournvita)", 18.0, False, "Cereal Preparations"),
    (19, "19021100", "Uncooked pasta not containing eggs", 12.0, False, "Cereal Preparations"),
    (19, "19021900", "Other uncooked pasta", 12.0, False, "Cereal Preparations"),
    (19, "19023000", "Other pasta (cooked/frozen/stuffed) — Maggi, Yippee instant noodles", 12.0, False, "Cereal Preparations"),
    (19, "19024000", "Couscous", 12.0, False, "Cereal Preparations"),
    (19, "19031000", "Tapioca and substitutes from starch, in flakes", 18.0, False, "Cereal Preparations"),
    (19, "19041000", "Prepared foods (corn flakes, puffed rice, muesli)", 18.0, False, "Cereal Preparations"),
    (19, "19042000", "Prepared foods from unroasted cereal flakes", 18.0, False, "Cereal Preparations"),
    (19, "19049000", "Other prepared cereals and similar preparations", 18.0, False, "Cereal Preparations"),
    (19, "19051000", "Crispbread", 18.0, False, "Cereal Preparations"),
    (19, "19052000", "Gingerbread and similar", 18.0, False, "Cereal Preparations"),
    (19, "19053100", "Sweet biscuits — Britannia, Parle-G, Sunfeast, Oreo", 18.0, False, "Cereal Preparations"),
    (19, "19053200", "Waffles and wafers", 18.0, False, "Cereal Preparations"),
    (19, "19054000", "Rusks, toasted bread", 18.0, False, "Cereal Preparations"),
    (19, "19059010", "Bread, other than pizza base", 18.0, False, "Cereal Preparations"),
    (19, "19059090", "Other bakers wares — Kurkure, Cheetos type", 18.0, False, "Cereal Preparations"),
    # ── Chapter 20 — Vegetables/Fruits Preparations ───────────────────────
    (20, "20019000", "Other vegetables/fruit prepared/preserved in vinegar", 12.0, False, "Prepared Vegetables"),
    (20, "20029000", "Other tomatoes, prepared/preserved", 12.0, False, "Prepared Vegetables"),
    (20, "20052000", "Potato chips/crisps — Lays, Pringles", 12.0, False, "Prepared Vegetables"),
    (20, "20058000", "Sweet corn, prepared/preserved", 12.0, False, "Prepared Vegetables"),
    (20, "20071000", "Homogenised preparations", 12.0, False, "Prepared Vegetables"),
    (20, "20079100", "Citrus fruit jam, jelly, marmalade", 12.0, False, "Prepared Vegetables"),
    (20, "20092900", "Pineapple juice", 12.0, False, "Prepared Vegetables"),
    (20, "20094900", "Tomato juice", 12.0, False, "Prepared Vegetables"),
    (20, "20097900", "Apple juice", 12.0, False, "Prepared Vegetables"),
    (20, "20098990", "Mixed fruit juice (Real, Tropicana)", 12.0, False, "Prepared Vegetables"),
    # ── Chapter 21 — Misc Food Preparations ───────────────────────────────
    (21, "21011100", "Extracts/essences of coffee — Nescafe, Bru instant coffee", 12.0, False, "Misc Food"),
    (21, "21011200", "Preparations based on coffee extracts", 12.0, False, "Misc Food"),
    (21, "21012000", "Extracts/essences of tea/mate", 12.0, False, "Misc Food"),
    (21, "21031000", "Soya sauce", 12.0, False, "Misc Food"),
    (21, "21032000", "Tomato ketchup and other tomato sauces", 12.0, False, "Misc Food"),
    (21, "21033000", "Mustard flour/meal and prepared mustard", 12.0, False, "Misc Food"),
    (21, "21039000", "Other sauces and preparations", 12.0, False, "Misc Food"),
    (21, "21041000", "Soups and broths (Knorr, Maggi soup)", 18.0, False, "Misc Food"),
    (21, "21042000", "Homogenised composite food preparations — snacks (Lays chips type)", 18.0, False, "Misc Food"),
    (21, "21050000", "Ice cream and edible ice", 18.0, False, "Misc Food"),
    (21, "21061000", "Protein concentrates and textured protein substances", 18.0, False, "Misc Food"),
    (21, "21069011", "Pan masala not containing tobacco", 0.0, True, "Misc Food"),
    (21, "21069099", "Food preparations not elsewhere specified — other", 18.0, False, "Misc Food"),
    # ── Chapter 22 — Beverages ─────────────────────────────────────────────
    (22, "22011000", "Mineral waters and aerated waters (Bisleri, Himalaya Water)", 18.0, False, "Beverages"),
    (22, "22019000", "Other waters (not sweetened/flavoured)", 0.0, False, "Beverages"),
    (22, "22021010", "Aerated beverages (Coca-Cola, Pepsi, Thums Up, Sprite, Fanta, 7UP)", 28.0, True, "Beverages"),
    (22, "22021020", "Fruit pulp or fruit juice based drinks", 12.0, False, "Beverages"),
    (22, "22029990", "Other non-alcoholic beverages (Maaza, Frooti, Appy, Paper Boat)", 12.0, False, "Beverages"),
    (22, "22030000", "Beer made from malt", 28.0, True, "Beverages"),
    (22, "22042100", "Wine in containers up to 2 litres", 0.0, False, "Beverages"),
    (22, "22071000", "Undenatured ethyl alcohol >=80% vol", 18.0, False, "Beverages"),
    (22, "22082000", "Spirits obtained by distilling grape wine/grape marc", 28.0, True, "Beverages"),
    (22, "22089011", "Indian made foreign liquor (IMFL)", 28.0, True, "Beverages"),
    # ── Chapter 30 — Pharmaceutical Products ──────────────────────────────
    (30, "30021000", "Antisera and other blood fractions", 12.0, False, "Pharma"),
    (30, "30031000", "Medicaments containing penicillin, bulk", 12.0, False, "Pharma"),
    (30, "30039000", "Other medicaments for retail, bulk", 12.0, False, "Pharma"),
    (30, "30049011", "Paracetamol formulations — Dolo, Crocin, Calpol", 12.0, False, "Pharma"),
    (30, "30049012", "Aspirin/Disprin formulations", 12.0, False, "Pharma"),
    (30, "30049099", "Other medicaments for retail — Combiflam, Volini, Moov, Vicks", 12.0, False, "Pharma"),
    (30, "30051000", "Adhesive dressings (Hansaplast, Band-Aid)", 12.0, False, "Pharma"),
    (30, "30059000", "Other pharmaceutical wadding/gauze/bandages", 12.0, False, "Pharma"),
    (30, "30061000", "Sterile surgical catgut, sutures", 12.0, False, "Pharma"),
    (30, "30062000", "Blood grouping reagents", 12.0, False, "Pharma"),
    (30, "30064000", "Dental cements, other dental fillings", 12.0, False, "Pharma"),
    (30, "30065000", "First-aid boxes and kits", 12.0, False, "Pharma"),
    # ── Chapter 31 — Fertilizers ───────────────────────────────────────────
    (31, "31010000", "Animal or vegetable fertilisers", 5.0, False, "Fertilizers"),
    (31, "31021000", "Urea", 5.0, False, "Fertilizers"),
    (31, "31031000", "Superphosphates", 5.0, False, "Fertilizers"),
    (31, "31051000", "Goods in tablets/similar forms or in packages <=10kg", 5.0, False, "Fertilizers"),
    # ── Chapter 33 — Personal Care / Cosmetics ────────────────────────────
    (33, "33011100", "Essential oils of bergamot", 18.0, False, "Personal Care"),
    (33, "33012900", "Other essential oils", 18.0, False, "Personal Care"),
    (33, "33021000", "Mixtures of odoriferous substances, beverages", 18.0, False, "Personal Care"),
    (33, "33030000", "Perfumes and toilet waters", 18.0, False, "Personal Care"),
    (33, "33041000", "Lip make-up preparations (Lakme, Maybelline lipstick)", 18.0, False, "Personal Care"),
    (33, "33042000", "Eye make-up preparations", 18.0, False, "Personal Care"),
    (33, "33043000", "Manicure/pedicure preparations", 18.0, False, "Personal Care"),
    (33, "33049100", "Powders (Ponds powder, talc)", 18.0, False, "Personal Care"),
    (33, "33049900", "Skincare creams — Fair & Lovely, Ponds, Nivea, Himalaya, Mamaearth", 18.0, False, "Personal Care"),
    (33, "33051000", "Shampoos — Head & Shoulders, Pantene, Dove, Sunsilk, Clinic Plus", 18.0, False, "Personal Care"),
    (33, "33052000", "Preparations for permanent waving/straightening", 18.0, False, "Personal Care"),
    (33, "33053000", "Hair lacquers", 18.0, False, "Personal Care"),
    (33, "33059000", "Other hair preparations — Parachute coconut oil, Livon", 18.0, False, "Personal Care"),
    (33, "33061000", "Toothpaste — Colgate, Pepsodent, Close-Up, Dabur Red, Sensodyne", 18.0, False, "Personal Care"),
    (33, "33062000", "Dental floss", 18.0, False, "Personal Care"),
    (33, "33069000", "Other oral hygiene preparations (mouthwash, Listerine)", 18.0, False, "Personal Care"),
    (33, "33071000", "Pre-shave/shaving preparations (Gillette foam)", 18.0, False, "Personal Care"),
    (33, "33072000", "Deodorants and antiperspirants — Rexona, Fogg, Engage, Axe", 18.0, False, "Personal Care"),
    (33, "33073000", "Perfumed bath/shower salts", 18.0, False, "Personal Care"),
    (33, "33074900", "Other products for care of skin (Vaseline, Himalaya baby)", 18.0, False, "Personal Care"),
    # ── Chapter 34 — Soaps & Detergents ───────────────────────────────────
    (34, "34011100", "Toilet soap — Dettol, Lifebuoy, Lux, Dove, Pears, Hamam, Santoor", 18.0, False, "Soaps & Detergents"),
    (34, "34011900", "Other soaps in various forms", 18.0, False, "Soaps & Detergents"),
    (34, "34012000", "Soap in other forms — household type", 18.0, False, "Soaps & Detergents"),
    (34, "34013000", "Organic surface-active products for washing skin", 18.0, False, "Soaps & Detergents"),
    (34, "34021100", "Anionic surface-active agents (SLS base)", 18.0, False, "Soaps & Detergents"),
    (34, "34022000", "Detergents — Surf Excel, Ariel, Tide, Rin, Nirma, Wheel, Vim", 18.0, False, "Soaps & Detergents"),
    (34, "34029090", "Other surface-active preparations (Harpic, Lizol, Domex, Colin)", 18.0, False, "Soaps & Detergents"),
    # ── Chapter 38 — Agricultural Chemicals ───────────────────────────────
    (38, "38081000", "Insecticides (Mortein, HIT)", 18.0, False, "Agri Chemicals"),
    (38, "38082000", "Fungicides", 18.0, False, "Agri Chemicals"),
    (38, "38083000", "Herbicides (Roundup)", 18.0, False, "Agri Chemicals"),
    (38, "38089400", "Disinfectants — Dettol, Savlon antiseptic", 18.0, False, "Agri Chemicals"),
    (38, "38089900", "Other pesticides/agrochemicals", 18.0, False, "Agri Chemicals"),
    # ── Chapter 39 — Plastics ──────────────────────────────────────────────
    (39, "39011000", "Polyethylene with density <0.94", 18.0, False, "Plastics"),
    (39, "39012000", "Polyethylene with density >=0.94", 18.0, False, "Plastics"),
    (39, "39021000", "Polypropylene", 18.0, False, "Plastics"),
    (39, "39231000", "Boxes and cases of plastics", 18.0, False, "Plastics"),
    (39, "39232900", "Plastic sacks/bags", 18.0, False, "Plastics"),
    (39, "39241000", "Tableware/kitchenware of plastics", 18.0, False, "Plastics"),
    # ── Chapter 48 — Paper Products ────────────────────────────────────────
    (48, "48182000", "Toilet tissue (tissue paper rolls) — Kirkland, Bounty", 18.0, False, "Paper"),
    (48, "48183000", "Tablecloths and serviettes of paper", 18.0, False, "Paper"),
    (48, "48185000", "Articles of apparel/accessories of paper", 12.0, False, "Paper"),
    (48, "48192000", "Folding cartons/boxes of non-corrugated paper", 18.0, False, "Paper"),
    # ── Chapter 49 — Books & Newspapers ───────────────────────────────────
    (49, "49011000", "Printed books (educational/other) — EXEMPT", 0.0, False, "Books & Print"),
    (49, "49019900", "Other printed books/brochures/pamphlets", 12.0, False, "Books & Print"),
    (49, "49021000", "Newspapers/journals, daily", 0.0, False, "Books & Print"),
    (49, "49040000", "Music, printed/in manuscript", 0.0, False, "Books & Print"),
    (49, "49051000", "Globes, printed", 12.0, False, "Books & Print"),
    (49, "49111000", "Trade advertising material, commercial catalogues", 18.0, False, "Books & Print"),
    # ── Chapter 56 — Textiles ──────────────────────────────────────────────
    (56, "56011000", "Sanitary towels/tampons — Stayfree, Whisper, Sofy", 12.0, False, "Textiles"),
    (56, "56012200", "Wadding of man-made fibres, other articles", 12.0, False, "Textiles"),
    # ── Chapter 61-62 — Clothing ───────────────────────────────────────────
    (61, "61091000", "T-shirts of cotton (>1000 INR) — 12%, <=1000 INR — 5%", 12.0, False, "Clothing"),
    (61, "61103000", "Jerseys/pullovers of man-made fibres", 12.0, False, "Clothing"),
    (61, "61161000", "Gloves impregnated coated", 12.0, False, "Clothing"),
    (62, "62034200", "Men trousers of cotton (jeans, trousers)", 12.0, False, "Clothing"),
    (62, "62044200", "Women dresses of cotton", 12.0, False, "Clothing"),
    # ── Chapter 64 — Footwear ──────────────────────────────────────────────
    (64, "64021100", "Ski boots and snowboard boots", 18.0, False, "Footwear"),
    (64, "64029900", "Sports shoes (>1000 INR) — Nike, Adidas, Puma, VKC", 18.0, False, "Footwear"),
    (64, "64039900", "Other footwear with leather uppers", 18.0, False, "Footwear"),
    (64, "64042000", "Footwear with rubber/plastics uppers, other", 18.0, False, "Footwear"),
    # ── Chapter 84 — Machinery & Appliances ──────────────────────────────
    (84, "84151000", "Air conditioning machines — Daikin, Voltas, LG AC, Samsung AC", 28.0, False, "Electronics"),
    (84, "84186100", "Heat pumps other than air conditioning machines", 28.0, False, "Electronics"),
    (84, "84211100", "Cream separators", 18.0, False, "Electronics"),
    (84, "84501100", "Washing machines, household, fully automatic — Samsung, LG, Whirlpool", 28.0, False, "Electronics"),
    (84, "84509000", "Parts of washing machines", 18.0, False, "Electronics"),
    (84, "84713000", "Portable automatic data processing machines (Laptops) — Apple MacBook, Dell, HP, Lenovo", 18.0, False, "Electronics"),
    (84, "84715000", "Processing units (desktop computers)", 18.0, False, "Electronics"),
    (84, "84716000", "Input/output units (keyboard/mouse)", 18.0, False, "Electronics"),
    (84, "84733000", "Parts/accessories for ADP machines", 18.0, False, "Electronics"),
    (84, "84748000", "Other machinery for agglomerated mineral fuels", 18.0, False, "Electronics"),
    # ── Chapter 85 — Electrical Equipment ────────────────────────────────
    (85, "85044000", "Static converters/chargers (phone chargers, power banks)", 18.0, False, "Electronics"),
    (85, "85051100", "Permanent magnets (ferrite)", 18.0, False, "Electronics"),
    (85, "85065000", "Lithium-ion batteries (Li-ion) — Duracell, Eveready", 18.0, False, "Electronics"),
    (85, "85094000", "Food mixers/grinders (Preethi, Butterfly, Havells)", 18.0, False, "Electronics"),
    (85, "85161000", "Electric instantaneous/storage water heaters", 28.0, False, "Electronics"),
    (85, "85164000", "Electric smoothing irons", 18.0, False, "Electronics"),
    (85, "85166000", "Electric ovens/cookers/grills (microwave — LG, Samsung)", 28.0, False, "Electronics"),
    (85, "85171200", "Mobile phones (smartphones) — Apple iPhone, Samsung Galaxy, Xiaomi, OnePlus", 18.0, False, "Electronics"),
    (85, "85176200", "Base stations (network equipment)", 18.0, False, "Electronics"),
    (85, "85177000", "Parts for telephone sets/apparatus", 18.0, False, "Electronics"),
    (85, "85258090", "Digital cameras", 28.0, False, "Electronics"),
    (85, "85271200", "Pocket-size radio cassette-players", 18.0, False, "Electronics"),
    (85, "85287200", "LCD/LED/OLED TV sets — Samsung TV, LG TV, Sony Bravia, Mi TV", 28.0, False, "Electronics"),
    (85, "85414000", "Solar cells (photovoltaic)", 0.0, False, "Electronics"),
    # ── Chapter 87 — Automobiles ──────────────────────────────────────────
    (87, "87032190", "Motor cars, petrol <=1000cc — Maruti Alto, Hyundai Santro", 28.0, True, "Automobiles"),
    (87, "87032290", "Motor cars, petrol >1000cc <=1500cc — Swift, i20", 28.0, True, "Automobiles"),
    (87, "87032390", "Motor cars, petrol >1500cc — Innova, City", 28.0, True, "Automobiles"),
    (87, "87033290", "Motor cars, diesel >1500cc <=2500cc — Fortuner, XUV500", 28.0, True, "Automobiles"),
    (87, "87039020", "Electric motor vehicles (EV) — Tata Nexon EV", 5.0, False, "Automobiles"),
    (87, "87112000", "Motorcycles, engine >50cc <=250cc — Hero, Bajaj, TVS", 28.0, True, "Automobiles"),
    (87, "87113000", "Motorcycles, engine >250cc <=500cc — Royal Enfield", 28.0, True, "Automobiles"),
    (87, "87149900", "Parts and accessories for bicycles", 12.0, False, "Automobiles"),
    # ── SAC Codes — Services ───────────────────────────────────────────────
    (99, "9954", "Construction services", 18.0, False, "Services"),
    (99, "9963", "Accommodation and hotel services", 18.0, False, "Services"),
    (99, "9972", "Real estate services", 18.0, False, "Services"),
    (99, "9983", "Other professional, technical and business services (IT services)", 18.0, False, "Services"),
    (99, "9984", "Telecommunications, broadcasting and information supply services", 18.0, False, "Services"),
    (99, "9985", "Support services", 18.0, False, "Services"),
    (99, "9997", "Education services — EXEMPT", 0.0, False, "Services"),
    (99, "9971", "Financial and related services (Insurance — LIC, HDFC Life)", 18.0, False, "Services"),
]

# ---------------------------------------------------------------------------
# Brand aliases — FMCG brands → HSN codes  (for brand_aliases table)
# ---------------------------------------------------------------------------
_BRAND_ALIASES_FULL = [
    # (brand_name, category, hsn_code, gst_rate, cess_applicable, verified_source)
    # ── Health Drinks ──
    ("HORLICKS", "Health Drinks", "19019090", 18.0, False, "CBIC HSN 2024-25"),
    ("BOOST", "Health Drinks", "19019090", 18.0, False, "CBIC HSN 2024-25"),
    ("COMPLAN", "Health Drinks", "19019090", 18.0, False, "CBIC HSN 2024-25"),
    ("BOURNVITA", "Health Drinks", "19019090", 18.0, False, "CBIC HSN 2024-25"),
    ("OVALTINE", "Health Drinks", "19019090", 18.0, False, "CBIC HSN 2024-25"),
    ("MILO", "Health Drinks", "19019090", 18.0, False, "CBIC HSN 2024-25"),
    ("PEDIASURE", "Health Drinks", "19011010", 18.0, False, "CBIC HSN 2024-25"),
    ("ENSURE", "Health Drinks", "19011010", 18.0, False, "CBIC HSN 2024-25"),
    ("PROTEINEX", "Health Drinks", "19011090", 18.0, False, "CBIC HSN 2024-25"),
    ("HERBALIFE", "Health Drinks", "19011090", 18.0, False, "CBIC HSN 2024-25"),
    ("OZIVA", "Health Drinks", "19011090", 18.0, False, "CBIC HSN 2024-25"),
    ("SIMILAC", "Health Drinks", "19011010", 18.0, False, "CBIC HSN 2024-25"),
    # ── Biscuits ──
    ("BRITANNIA GOOD DAY", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("BRITANNIA MARIE GOLD", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("PARLE-G", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("PARLE G", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("OREO", "Biscuits", "19053200", 18.0, False, "CBIC HSN 2024-25"),
    ("SUNFEAST DARK FANTASY", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("HIDE AND SEEK", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("BOURBON", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("KRACKJACK", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("MONACO", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("THREPTIN", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("MCVITIES DIGESTIVE", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("UNIBIC", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("GOOD DAY", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    ("MARIE GOLD", "Biscuits", "19053100", 18.0, False, "CBIC HSN 2024-25"),
    # ── Noodles & Pasta ──
    ("MAGGI", "Noodles", "19023000", 12.0, False, "CBIC HSN 2024-25"),
    ("YIPPEE", "Noodles", "19023000", 12.0, False, "CBIC HSN 2024-25"),
    ("KNORR", "Noodles", "21041000", 18.0, False, "CBIC HSN 2024-25"),
    ("TOP RAMEN", "Noodles", "19023000", 12.0, False, "CBIC HSN 2024-25"),
    ("PATANJALI NOODLES", "Noodles", "19023000", 12.0, False, "CBIC HSN 2024-25"),
    ("BAMBINO", "Noodles", "19023000", 12.0, False, "CBIC HSN 2024-25"),
    ("INDOMIE", "Noodles", "19023000", 12.0, False, "CBIC HSN 2024-25"),
    # ── Chips & Snacks ──
    ("LAYS", "Chips & Snacks", "20052000", 12.0, False, "CBIC HSN 2024-25"),
    ("KURKURE", "Chips & Snacks", "19059090", 18.0, False, "CBIC HSN 2024-25"),
    ("PRINGLES", "Chips & Snacks", "20052000", 12.0, False, "CBIC HSN 2024-25"),
    ("HALDIRAMS", "Chips & Snacks", "19041090", 18.0, False, "CBIC HSN 2024-25"),
    ("BINGO", "Chips & Snacks", "19059090", 18.0, False, "CBIC HSN 2024-25"),
    ("ACT II POPCORN", "Chips & Snacks", "21042000", 18.0, False, "CBIC HSN 2024-25"),
    ("TOO YUMM", "Chips & Snacks", "19059090", 18.0, False, "CBIC HSN 2024-25"),
    ("CORNITOS", "Chips & Snacks", "19059090", 18.0, False, "CBIC HSN 2024-25"),
    ("BIKAJI", "Chips & Snacks", "19041090", 18.0, False, "CBIC HSN 2024-25"),
    ("BALAJI", "Chips & Snacks", "19041090", 18.0, False, "CBIC HSN 2024-25"),
    # ── Soft Drinks ──
    ("COCA COLA", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("COCA-COLA", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("PEPSI", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("THUMS UP", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("LIMCA", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("SPRITE", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("FANTA", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("7UP", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("MOUNTAIN DEW", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("MIRINDA", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("MAAZA", "Soft Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("FROOTI", "Soft Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("SLICE", "Soft Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("REAL JUICE", "Soft Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("PAPER BOAT", "Soft Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("B NATURAL", "Soft Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("APPY FIZZ", "Soft Drinks", "22021010", 28.0, True, "CBIC HSN 2024-25"),
    ("KINLEY", "Water", "22011000", 18.0, False, "CBIC HSN 2024-25"),
    ("BISLERI", "Water", "22011000", 18.0, False, "CBIC HSN 2024-25"),
    ("AQUAFINA", "Water", "22011000", 18.0, False, "CBIC HSN 2024-25"),
    ("HIMALAYA WATER", "Water", "22011000", 18.0, False, "CBIC HSN 2024-25"),
    ("RED BULL", "Energy Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    ("MONSTER", "Energy Drinks", "22029990", 12.0, False, "CBIC HSN 2024-25"),
    # ── Dairy ──
    ("AMUL", "Dairy", "04029900", 5.0, False, "CBIC HSN 2024-25"),
    ("MOTHER DAIRY", "Dairy", "04011000", 0.0, False, "CBIC HSN 2024-25"),
    ("NANDINI", "Dairy", "04011000", 0.0, False, "CBIC HSN 2024-25"),
    ("MILMA", "Dairy", "04011000", 0.0, False, "CBIC HSN 2024-25"),
    ("PARAG", "Dairy", "04029900", 5.0, False, "CBIC HSN 2024-25"),
    ("GOWARDHAN", "Dairy", "04029900", 5.0, False, "CBIC HSN 2024-25"),
    ("HERITAGE DAIRY", "Dairy", "04029900", 5.0, False, "CBIC HSN 2024-25"),
    ("NESTLE MUNCH", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("KITKAT", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("KIT KAT", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("DAIRY MILK", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("CADBURY DAIRY MILK", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("5 STAR", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("FERRERO ROCHER", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("SNICKERS", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("BOUNTY", "Chocolates", "18063200", 28.0, False, "CBIC HSN 2024-25"),
    ("NUTELLA", "Chocolates", "18069000", 18.0, False, "CBIC HSN 2024-25"),
    # ── Toothpaste ──
    ("COLGATE", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("PEPSODENT", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("CLOSE UP", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("CLOSE-UP", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("SENSODYNE", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("DABUR RED", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("PATANJALI DANT KANTI", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("HIMALAYA TOOTHPASTE", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("VICCO VAJRADANTI", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("MESWAK", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    ("ORAL B", "Toothpaste", "33061000", 18.0, False, "CBIC HSN 2024-25"),
    # ── Shampoo ──
    ("HEAD AND SHOULDERS", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("HEAD & SHOULDERS", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("PANTENE", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("DOVE SHAMPOO", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("CLINIC PLUS", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("SUNSILK", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("LOREAL", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("TRESEMME", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("HIMALAYA SHAMPOO", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("BIOTIQUE", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("MAMAEARTH SHAMPOO", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("WOW SHAMPOO", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("INDULEKHA", "Shampoo", "33051000", 18.0, False, "CBIC HSN 2024-25"),
    ("PARACHUTE", "Hair Oil", "33059000", 18.0, False, "CBIC HSN 2024-25"),
    ("VATIKA", "Hair Oil", "33059000", 18.0, False, "CBIC HSN 2024-25"),
    ("LIVON", "Hair Serum", "33059000", 18.0, False, "CBIC HSN 2024-25"),
    # ── Soap ──
    ("DETTOL SOAP", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("DETTOL", "Antiseptic", "38089400", 18.0, False, "CBIC HSN 2024-25"),
    ("LIFEBUOY", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("LUX", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("DOVE", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("PEARS", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("HAMAM", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("CINTHOL", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("SANTOOR", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("GODREJ NO 1", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("NIRMA SOAP", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("SAVLON", "Antiseptic", "38089400", 18.0, False, "CBIC HSN 2024-25"),
    ("HIMALAYA SOAP", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("FIAMA", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("MEDIMIX", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    ("CHANDRIKA", "Soap", "34011100", 18.0, False, "CBIC HSN 2024-25"),
    # ── Detergent ──
    ("SURF EXCEL", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("ARIEL", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("TIDE", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("RIN", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("NIRMA DETERGENT", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("WHEEL", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("VIM", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("HARPIC", "Cleaner", "34029090", 18.0, False, "CBIC HSN 2024-25"),
    ("DOMEX", "Cleaner", "34029090", 18.0, False, "CBIC HSN 2024-25"),
    ("COLIN", "Cleaner", "34029090", 18.0, False, "CBIC HSN 2024-25"),
    ("LIZOL", "Cleaner", "34029090", 18.0, False, "CBIC HSN 2024-25"),
    ("SCOTCH BRITE", "Cleaner", "34029090", 18.0, False, "CBIC HSN 2024-25"),
    ("EXO", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    ("PRIL", "Detergent", "34022000", 18.0, False, "CBIC HSN 2024-25"),
    # ── Skincare ──
    ("FAIR AND LOVELY", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("GLOW AND LOVELY", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("PONDS", "Skincare", "33049100", 18.0, False, "CBIC HSN 2024-25"),
    ("LAKME", "Skincare", "33041000", 18.0, False, "CBIC HSN 2024-25"),
    ("OLAY", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("HIMALAYA CREAM", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("MAMAEARTH", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("PLUM", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("WOW SKINCARE", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("FOREST ESSENTIALS", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("LOTUS HERBALS", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("VLCC", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("VASELINE", "Skincare", "27121090", 18.0, False, "CBIC HSN 2024-25"),
    ("NIVEA", "Skincare", "33049100", 18.0, False, "CBIC HSN 2024-25"),
    ("CETAPHIL", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("GARNIER", "Skincare", "33049900", 18.0, False, "CBIC HSN 2024-25"),
    ("MAYBELLINE", "Cosmetics", "33041000", 18.0, False, "CBIC HSN 2024-25"),
    ("GILLETTE", "Shaving", "33071000", 18.0, False, "CBIC HSN 2024-25"),
    ("FOGG", "Deodorant", "33072000", 18.0, False, "CBIC HSN 2024-25"),
    ("ENGAGE", "Deodorant", "33072000", 18.0, False, "CBIC HSN 2024-25"),
    ("AXE", "Deodorant", "33072000", 18.0, False, "CBIC HSN 2024-25"),
    ("REXONA", "Deodorant", "33072000", 18.0, False, "CBIC HSN 2024-25"),
    # ── OTC Medicines ──
    ("CROCIN", "OTC Medicine", "30049011", 12.0, False, "CBIC HSN 2024-25"),
    ("DOLO", "OTC Medicine", "30049011", 12.0, False, "CBIC HSN 2024-25"),
    ("DOLO 650", "OTC Medicine", "30049011", 12.0, False, "CBIC HSN 2024-25"),
    ("COMBIFLAM", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("SARIDON", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("DISPRIN", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("VOLINI", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("MOOV", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("IODEX", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("VICKS", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("ZANDU BALM", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("AMRUTANJAN", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("BURNOL", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("BETADINE", "OTC Medicine", "30049099", 12.0, False, "CBIC HSN 2024-25"),
    ("BAND AID", "Medical Supplies", "30051000", 12.0, False, "CBIC HSN 2024-25"),
    ("HANSAPLAST", "Medical Supplies", "30051000", 12.0, False, "CBIC HSN 2024-25"),
    # ── Mobile Phones ──
    ("APPLE IPHONE", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("IPHONE", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("SAMSUNG GALAXY", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("ONEPLUS", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("XIAOMI REDMI", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("POCO", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("REALME", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("VIVO", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("OPPO", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("IQOO", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("NOTHING PHONE", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("MOTOROLA", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    ("NOKIA", "Mobile Phones", "85171200", 18.0, False, "CBIC HSN 2024-25"),
    # ── Laptops ──
    ("MACBOOK", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("APPLE MACBOOK", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("DELL LAPTOP", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("HP LAPTOP", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("LENOVO", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("ASUS", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("ACER", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    ("MSI", "Laptops", "84713000", 18.0, False, "CBIC HSN 2024-25"),
    # ── TVs ──
    ("SAMSUNG TV", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("LG TV", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("SONY BRAVIA", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("MI TV", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("VU TV", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("ONEPLUS TV", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("TCL", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("HISENSE", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("PANASONIC TV", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    ("THOMSON", "Television", "85287200", 28.0, False, "CBIC HSN 2024-25"),
    # ── ACs ──
    ("DAIKIN", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("VOLTAS", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("LG AC", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("SAMSUNG AC", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("HITACHI AC", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("BLUE STAR", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("LLOYD AC", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("GODREJ AC", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    ("O GENERAL", "Air Conditioner", "84151000", 28.0, False, "CBIC HSN 2024-25"),
    # ── Edible Oil ──
    ("FORTUNE OIL", "Edible Oil", "15179010", 5.0, False, "CBIC HSN 2024-25"),
    ("SAFFOLA", "Edible Oil", "15121910", 5.0, False, "CBIC HSN 2024-25"),
    ("DHARA", "Edible Oil", "15081000", 5.0, False, "CBIC HSN 2024-25"),
    ("SUNDROP", "Edible Oil", "15121910", 5.0, False, "CBIC HSN 2024-25"),
    ("GEMINI OIL", "Edible Oil", "15179010", 5.0, False, "CBIC HSN 2024-25"),
    ("PARACHUTE COCONUT OIL", "Edible Oil", "15132900", 5.0, False, "CBIC HSN 2024-25"),
    ("KLF COCONAD", "Edible Oil", "15132900", 5.0, False, "CBIC HSN 2024-25"),
    # ── Spices ──
    ("MDH", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("EVEREST", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("CATCH", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("SUHANA", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("BADSHAH MASALA", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("EASTERN", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("MTR MASALA", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("AASHIRVAAD MASALA", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    ("BRAHMINS", "Spices", "09109910", 5.0, False, "CBIC HSN 2024-25"),
    # ── Rice & Grains ──
    ("INDIA GATE", "Rice", "10063000", 5.0, False, "CBIC HSN 2024-25"),
    ("KOHINOOR", "Rice", "10063000", 5.0, False, "CBIC HSN 2024-25"),
    ("DAAWAT", "Rice", "10063000", 5.0, False, "CBIC HSN 2024-25"),
    ("PATANJALI RICE", "Rice", "10063000", 5.0, False, "CBIC HSN 2024-25"),
    ("LAL QILLA", "Rice", "10063000", 5.0, False, "CBIC HSN 2024-25"),
    # ── Atta/Flour ──
    ("AASHIRVAAD ATTA", "Flour", "11010000", 5.0, False, "CBIC HSN 2024-25"),
    ("ANNAPURNA ATTA", "Flour", "11010000", 5.0, False, "CBIC HSN 2024-25"),
    ("PILLSBURY", "Flour", "11010000", 5.0, False, "CBIC HSN 2024-25"),
    ("SHAKTI BHOG", "Flour", "11010000", 5.0, False, "CBIC HSN 2024-25"),
    ("PATANJALI ATTA", "Flour", "11010000", 5.0, False, "CBIC HSN 2024-25"),
    ("NATURE FRESH ATTA", "Flour", "11010000", 5.0, False, "CBIC HSN 2024-25"),
    # ── Tea ──
    ("TATA TEA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("BROOKE BOND RED LABEL", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("RED LABEL", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("LIPTON", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("WAGH BAKRI", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("TAJ MAHAL TEA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("SOCIETY TEA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("PATANJALI TEA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("GIRNAR TEA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("TETLEY", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("ORGANIC INDIA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    ("AVT TEA", "Tea", "09021000", 5.0, False, "CBIC HSN 2024-25"),
    # ── Coffee ──
    ("NESCAFE", "Coffee", "21011100", 12.0, False, "CBIC HSN 2024-25"),
    ("BRU", "Coffee", "21011100", 12.0, False, "CBIC HSN 2024-25"),
    ("DAVIDOFF", "Coffee", "21011100", 12.0, False, "CBIC HSN 2024-25"),
    ("TATA COFFEE", "Coffee", "21011100", 12.0, False, "CBIC HSN 2024-25"),
    ("BLUE TOKAI", "Coffee", "21011100", 12.0, False, "CBIC HSN 2024-25"),
    ("SLEEPY OWL", "Coffee", "21011100", 12.0, False, "CBIC HSN 2024-25"),
    # ── Baby Products ──
    ("PAMPERS", "Baby Products", "56011000", 12.0, False, "CBIC HSN 2024-25"),
    ("HUGGIES", "Baby Products", "56011000", 12.0, False, "CBIC HSN 2024-25"),
    ("MAMY POKO", "Baby Products", "56011000", 12.0, False, "CBIC HSN 2024-25"),
    ("HIMALAYA BABY", "Baby Products", "33074900", 18.0, False, "CBIC HSN 2024-25"),
    ("JOHNSONS BABY", "Baby Products", "33074900", 18.0, False, "CBIC HSN 2024-25"),
    ("MAMAEARTH BABY", "Baby Products", "33074900", 18.0, False, "CBIC HSN 2024-25"),
    ("PIGEON", "Baby Products", "33074900", 18.0, False, "CBIC HSN 2024-25"),
    # ── Automobiles ──
    ("MARUTI SUZUKI", "Automobiles", "87032190", 28.0, True, "CBIC HSN 2024-25"),
    ("HYUNDAI", "Automobiles", "87032290", 28.0, True, "CBIC HSN 2024-25"),
    ("TATA MOTORS", "Automobiles", "87032290", 28.0, True, "CBIC HSN 2024-25"),
    ("MAHINDRA", "Automobiles", "87033290", 28.0, True, "CBIC HSN 2024-25"),
    ("HONDA", "Automobiles", "87032290", 28.0, True, "CBIC HSN 2024-25"),
    ("TOYOTA", "Automobiles", "87032390", 28.0, True, "CBIC HSN 2024-25"),
    ("KIA", "Automobiles", "87032290", 28.0, True, "CBIC HSN 2024-25"),
    ("HERO BIKE", "Motorcycles", "87112000", 28.0, True, "CBIC HSN 2024-25"),
    ("BAJAJ BIKE", "Motorcycles", "87112000", 28.0, True, "CBIC HSN 2024-25"),
    ("TVS", "Motorcycles", "87112000", 28.0, True, "CBIC HSN 2024-25"),
    ("ROYAL ENFIELD", "Motorcycles", "87113000", 28.0, True, "CBIC HSN 2024-25"),
]

# ---------------------------------------------------------------------------
# Keyword → HSN mapping (for Tier-4 keyword search)
# ---------------------------------------------------------------------------
_KEYWORD_MAP = [
    # (keyword, hsn_code, category, description)
    ("malt drink", "19019090", "Health Drinks", "Malt-based health drink"),
    ("health drink", "19019090", "Health Drinks", "Malt-based health drink"),
    ("malted milk", "19019090", "Health Drinks", "Malted milk preparations"),
    ("infant formula", "19011010", "Baby Food", "Preparations for infants"),
    ("baby food", "19011010", "Baby Food", "Infant food preparations"),
    ("corn flakes", "19041000", "Cereals", "Corn flakes and puffed cereals"),
    ("puffed rice", "19041000", "Cereals", "Puffed rice/corn preparations"),
    ("muesli", "19041000", "Cereals", "Muesli and similar cereals"),
    ("biscuit", "19053100", "Biscuits", "Sweet biscuits"),
    ("cookie", "19053100", "Biscuits", "Biscuits and cookies"),
    ("cracker", "19053100", "Biscuits", "Crackers and savoury biscuits"),
    ("noodle", "19023000", "Noodles", "Instant noodles"),
    ("instant noodle", "19023000", "Noodles", "Instant noodles"),
    ("pasta", "19023000", "Noodles", "Pasta and similar"),
    ("shampoo", "33051000", "Hair Care", "Shampoos"),
    ("hair wash", "33051000", "Hair Care", "Hair washing products"),
    ("hair shampoo", "33051000", "Hair Care", "Hair shampoo"),
    ("conditioner", "33051000", "Hair Care", "Hair conditioner"),
    ("toothpaste", "33061000", "Oral Care", "Toothpaste"),
    ("dental cream", "33061000", "Oral Care", "Dental creams"),
    ("tooth paste", "33061000", "Oral Care", "Toothpaste"),
    ("soap", "34011100", "Soap", "Toilet soap"),
    ("handwash", "34011100", "Soap", "Handwash soap"),
    ("bath soap", "34011100", "Soap", "Bath soap"),
    ("detergent", "34022000", "Detergent", "Washing/laundry detergent"),
    ("washing powder", "34022000", "Detergent", "Washing powder"),
    ("laundry", "34022000", "Detergent", "Laundry detergent"),
    ("dishwash", "34022000", "Detergent", "Dishwashing agent"),
    ("mobile phone", "85171200", "Electronics", "Mobile phones/smartphones"),
    ("smartphone", "85171200", "Electronics", "Smartphones"),
    ("cell phone", "85171200", "Electronics", "Mobile phones"),
    ("laptop", "84713000", "Electronics", "Laptop computers"),
    ("notebook computer", "84713000", "Electronics", "Notebook/laptop"),
    ("computer", "84713000", "Electronics", "Personal computers"),
    ("television", "85287200", "Electronics", "Television sets"),
    ("tv set", "85287200", "Electronics", "TV/television"),
    ("led tv", "85287200", "Electronics", "LED television"),
    ("lcd tv", "85287200", "Electronics", "LCD television"),
    ("air conditioner", "84151000", "Electronics", "Air conditioning units"),
    ("ac unit", "84151000", "Electronics", "Air conditioner"),
    ("split ac", "84151000", "Electronics", "Split air conditioner"),
    ("washing machine", "84501100", "Electronics", "Washing machines"),
    ("chips", "20052000", "Snacks", "Potato chips"),
    ("potato chips", "20052000", "Snacks", "Potato chips crisps"),
    ("snack", "21042000", "Snacks", "Food snacks"),
    ("namkeen", "19041090", "Snacks", "Namkeen and fried snacks"),
    ("medicine", "30049099", "Pharma", "General medicines"),
    ("tablet", "30049099", "Pharma", "Pharmaceutical tablets"),
    ("capsule", "30049099", "Pharma", "Pharmaceutical capsules"),
    ("syrup", "30049099", "Pharma", "Pharmaceutical syrups"),
    ("paracetamol", "30049011", "Pharma", "Paracetamol formulations"),
    ("soft drink", "22021010", "Beverages", "Aerated soft drinks"),
    ("aerated drink", "22021010", "Beverages", "Aerated beverages"),
    ("cola", "22021010", "Beverages", "Cola beverages"),
    ("mineral water", "22011000", "Water", "Packaged mineral water"),
    ("packaged water", "22011000", "Water", "Packaged drinking water"),
    ("drinking water", "22011000", "Water", "Packaged drinking water"),
    ("coconut oil", "15132900", "Edible Oil", "Refined coconut oil"),
    ("edible oil", "15179010", "Edible Oil", "Refined blended edible oil"),
    ("cooking oil", "15179010", "Edible Oil", "Cooking/edible oil"),
    ("skincare cream", "33049900", "Skincare", "Skincare preparations"),
    ("face cream", "33049900", "Skincare", "Face cream/moisturiser"),
    ("moisturiser", "33049900", "Skincare", "Moisturising cream"),
    ("deodorant", "33072000", "Deodorant", "Deodorants/antiperspirants"),
    ("perfume", "33030000", "Perfume", "Perfumes and toilet waters"),
    ("rice", "10063000", "Cereals", "Milled rice"),
    ("basmati", "10063000", "Cereals", "Basmati rice"),
    ("flour", "11010000", "Milling", "Wheat flour"),
    ("atta", "11010000", "Milling", "Wheat flour (atta)"),
    ("tea", "09021000", "Tea", "Tea leaves"),
    ("green tea", "09021000", "Tea", "Green tea"),
    ("coffee", "21011100", "Coffee", "Instant coffee"),
    ("masala", "09109910", "Spices", "Spice blends/masala"),
    ("spice", "09109910", "Spices", "Spices and condiments"),
    ("diaper", "56011000", "Baby Products", "Baby diapers/nappies"),
    ("nappy", "56011000", "Baby Products", "Baby nappies"),
    ("antiseptic", "38089400", "Antiseptic", "Antiseptic preparations"),
    ("sanitizer", "38089400", "Antiseptic", "Hand sanitizer"),
    ("book", "49011000", "Books", "Printed books"),
    ("notebook", "49011000", "Books", "Printed books"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── Safety: abort if verified_products is empty ────────────────────────
    vp_count = conn.execute(sa.text("SELECT COUNT(*) FROM verified_products")).scalar()
    assert vp_count and int(vp_count) > 0, (
        "SAFETY ABORT: verified_products is empty. Refusing to run migration."
    )
    hsn_count = conn.execute(sa.text("SELECT COUNT(*) FROM hsn_codes")).scalar()
    assert hsn_count and int(hsn_count) > 0, (
        "SAFETY ABORT: hsn_codes is empty. Refusing to run migration."
    )

    # ── Step 1: Create brand_aliases table (if not exists) ──────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS brand_aliases (
            id                SERIAL PRIMARY KEY,
            brand_name        VARCHAR(200) NOT NULL,
            brand_name_upper  VARCHAR(200) NOT NULL,
            category          VARCHAR(100) NOT NULL,
            hsn_code          VARCHAR(10)  NOT NULL,
            gst_rate          FLOAT        NOT NULL,
            cess_applicable   BOOLEAN      NOT NULL DEFAULT FALSE,
            verified_source   VARCHAR(100) NOT NULL DEFAULT 'CBIC HSN 2024-25',
            is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
            last_updated      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_brand_alias UNIQUE (brand_name_upper, hsn_code)
        )
    """))

    # ── Step 2: Indexes for brand_aliases ───────────────────────────────────
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_brand_upper ON brand_aliases (brand_name_upper)"
    ))
    conn.execute(sa.text(
        "CREATE EXTENSION IF NOT EXISTS pg_trgm"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_brand_trgm ON brand_aliases "
        "USING GIN (brand_name_upper gin_trgm_ops)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_brand_alias_hsn ON brand_aliases (hsn_code)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_brand_alias_category ON brand_aliases (category)"
    ))

    # ── Step 3: Create keyword_category_map table ───────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS keyword_category_map (
            id          SERIAL PRIMARY KEY,
            keyword     VARCHAR(200) NOT NULL,
            hsn_code    VARCHAR(10)  NOT NULL,
            category    VARCHAR(100) NOT NULL,
            description TEXT,
            priority    INTEGER NOT NULL DEFAULT 0,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_keyword_hsn UNIQUE (keyword, hsn_code)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_keyword_map_kw ON keyword_category_map "
        "USING GIN (keyword gin_trgm_ops)"
    ))

    # ── Step 4: Create pending_review table ─────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS pending_review (
            id              SERIAL PRIMARY KEY,
            query           TEXT NOT NULL,
            query_normalized TEXT NOT NULL,
            best_guess_hsn  VARCHAR(10),
            best_guess_gst  FLOAT,
            confidence      FLOAT,
            tier_used       INTEGER,
            source          VARCHAR(100),
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            admin_notes     TEXT,
            resolved_hsn    VARCHAR(10),
            resolved_by     VARCHAR(100),
            resolved_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_pending_review_status "
        "ON pending_review (status, created_at DESC)"
    ))

    # ── Step 5: Create search_cache table ───────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS search_cache (
            id              SERIAL PRIMARY KEY,
            query_normalized TEXT NOT NULL UNIQUE,
            hsn_code        VARCHAR(10) NOT NULL,
            description     TEXT,
            gst_rate        FLOAT,
            cess_applicable BOOLEAN DEFAULT FALSE,
            confidence      FLOAT,
            tier_used       INTEGER,
            source          VARCHAR(100),
            hit_count       INTEGER NOT NULL DEFAULT 1,
            expires_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_search_cache_query "
        "ON search_cache (query_normalized)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_search_cache_expires "
        "ON search_cache (expires_at) WHERE expires_at IS NOT NULL"
    ))

    # ── Step 6: Add missing column to hsn_master if needed ──────────────────
    conn.execute(sa.text(
        "ALTER TABLE hsn_master ADD COLUMN IF NOT EXISTS cess_applicable BOOLEAN DEFAULT FALSE"
    ))
    conn.execute(sa.text(
        "ALTER TABLE hsn_master ADD COLUMN IF NOT EXISTS verified_source VARCHAR(100) DEFAULT 'CBIC HSN 2024-25'"
    ))
    conn.execute(sa.text(
        "ALTER TABLE hsn_master ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ DEFAULT NOW()"
    ))
    conn.execute(sa.text(
        "ALTER TABLE hsn_master ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"
    ))

    # ── Step 7: Populate hsn_master (INSERT ON CONFLICT DO UPDATE) ──────────
    for chapter, hsn_code, description, gst_rate, cess, category in _HSN_MASTER_ROWS:
        conn.execute(sa.text("""
            INSERT INTO hsn_master
                (hsn_code, description, gst_rate, chapter, category,
                 cess_applicable, verified_source, last_updated, is_active)
            VALUES
                (:hsn_code, :description, :gst_rate, :chapter, :category,
                 :cess, :vsrc, NOW(), TRUE)
            ON CONFLICT (hsn_code) DO UPDATE SET
                description    = EXCLUDED.description,
                gst_rate       = EXCLUDED.gst_rate,
                chapter        = EXCLUDED.chapter,
                category       = EXCLUDED.category,
                cess_applicable = EXCLUDED.cess_applicable,
                verified_source = EXCLUDED.verified_source,
                last_updated   = NOW()
        """), {
            "hsn_code": hsn_code,
            "description": description,
            "gst_rate": gst_rate,
            "chapter": chapter,
            "category": category,
            "cess": cess,
            "vsrc": "CBIC HSN 2024-25",
        })

    # ── Step 8: Populate brand_aliases (INSERT ON CONFLICT DO NOTHING) ──────
    for brand_name, category, hsn_code, gst_rate, cess, vsrc in _BRAND_ALIASES_FULL:
        conn.execute(sa.text("""
            INSERT INTO brand_aliases
                (brand_name, brand_name_upper, category, hsn_code,
                 gst_rate, cess_applicable, verified_source, last_updated)
            VALUES
                (:brand, :brand_upper, :category, :hsn_code,
                 :gst_rate, :cess, :vsrc, NOW())
            ON CONFLICT (brand_name_upper, hsn_code) DO UPDATE SET
                gst_rate       = EXCLUDED.gst_rate,
                cess_applicable = EXCLUDED.cess_applicable,
                verified_source = EXCLUDED.verified_source,
                last_updated   = NOW()
        """), {
            "brand": brand_name,
            "brand_upper": brand_name.upper().strip(),
            "category": category,
            "hsn_code": hsn_code,
            "gst_rate": gst_rate,
            "cess": cess,
            "vsrc": vsrc,
        })

    # ── Step 9: Populate keyword_category_map ────────────────────────────────
    for keyword, hsn_code, category, description in _KEYWORD_MAP:
        conn.execute(sa.text("""
            INSERT INTO keyword_category_map (keyword, hsn_code, category, description)
            VALUES (:kw, :hsn, :cat, :desc)
            ON CONFLICT (keyword, hsn_code) DO NOTHING
        """), {
            "kw": keyword.lower().strip(),
            "hsn": hsn_code,
            "cat": category,
            "desc": description,
        })

    # ── Step 10: Create compound index on verified_products for brand search ──
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_verified_brand_upper "
        "ON verified_products (UPPER(brand)) WHERE brand IS NOT NULL"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_verified_category "
        "ON verified_products (category) WHERE category IS NOT NULL"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    # Downgrade is intentionally minimal — we only remove the new tables
    # and indexes. We do NOT restore the hsn_master or brand_aliases data
    # since they are additive.
    conn.execute(sa.text("DROP TABLE IF EXISTS search_cache"))
    conn.execute(sa.text("DROP TABLE IF EXISTS pending_review"))
    conn.execute(sa.text("DROP TABLE IF EXISTS keyword_category_map"))
    conn.execute(sa.text("DROP TABLE IF EXISTS brand_aliases"))
