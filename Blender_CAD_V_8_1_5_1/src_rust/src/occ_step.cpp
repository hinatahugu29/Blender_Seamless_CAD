#include "occ_step.hpp"
#include "occ_utils.hpp"
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Mat.hxx>
#include <map>
#include <mutex>
#include <atomic>

namespace occ {

static std::map<std::string, TopoDS_Shape> g_step_cache;
static std::mutex g_step_mutex;
static std::atomic<uint64_t> g_step_counter(0);

TopoDS_Shape get_step_shape(const std::string& uuid) {
    std::lock_guard<std::mutex> lock(g_step_mutex);
    auto it = g_step_cache.find(uuid);
    if (it != g_step_cache.end()) {
        return it->second;
    }
    return TopoDS_Shape();
}

std::vector<std::string> import_step(const std::string& filepath, double scale) {
    std::vector<std::string> new_uuids;
    
    STEPControl_Reader reader;
    IFSelect_ReturnStatus status = reader.ReadFile(filepath.c_str());
    
    if (status != IFSelect_RetDone) {
        occ_core::log_debug("import_step: Failed to read STEP file: " + filepath);
        return new_uuids;
    }
    
    reader.TransferRoots();
    TopoDS_Shape result = reader.OneShape();
    
    std::vector<TopoDS_Shape> parts;
    
    TopExp_Explorer exp(result, TopAbs_SOLID);
    while (exp.More()) {
        parts.push_back(exp.Current());
        exp.Next();
    }
    
    if (parts.empty()) {
        exp.Init(result, TopAbs_SHELL);
        while (exp.More()) {
            parts.push_back(exp.Current());
            exp.Next();
        }
    }
    
    if (parts.empty()) {
        exp.Init(result, TopAbs_FACE);
        while (exp.More()) {
            parts.push_back(exp.Current());
            exp.Next();
        }
    }
    
    if (parts.empty() && !result.IsNull()) {
        parts.push_back(result);
    }
    
    const double safe_scale = std::max(scale, 1e-6);
    const bool apply_scale = std::abs(safe_scale - 1.0) > 1e-9;

    std::lock_guard<std::mutex> lock(g_step_mutex);
    for (const auto& part : parts) {
        std::string new_uuid = "step_part_" + std::to_string(++g_step_counter);
        TopoDS_Shape final_part = part;
        if (apply_scale && !part.IsNull()) {
            gp_GTrsf gt_scale;
            gt_scale.SetVectorialPart(gp_Mat(
                safe_scale, 0, 0,
                0, safe_scale, 0,
                0, 0, safe_scale
            ));
            final_part = BRepBuilderAPI_GTransform(part, gt_scale, true).Shape();
        }
        g_step_cache[new_uuid] = final_part;
        new_uuids.push_back(new_uuid);
    }
    
    return new_uuids;
}

bool export_step(const std::vector<std::string>& uuids, const std::string& filepath) {
    STEPControl_Writer writer;
    Interface_Static::SetIVal("write.step.schema", 4);
    
    bool has_shapes = false;
    for (const auto& uuid : uuids) {
        TopoDS_Shape shape = get_step_shape(uuid);
        if (!shape.IsNull()) {
            writer.Transfer(shape, STEPControl_AsIs);
            has_shapes = true;
        } else {
            occ_core::log_debug("export_step: Shape not found for UUID " + uuid);
        }
    }
    
    if (!has_shapes) {
        occ_core::log_debug("export_step: No valid shapes to export");
        return false;
    }
    
    IFSelect_ReturnStatus status = writer.Write(filepath.c_str());
    if (status != IFSelect_RetDone) {
        occ_core::log_debug("export_step: Failed to write STEP file: " + filepath);
        return false;
    }
    
    return true;
}

bool export_stack_to_step(void* stack_ptr, const std::string& filepath, double scale) {
    if (!stack_ptr) return false;
    occ_core::CADStack* stack = static_cast<occ_core::CADStack*>(stack_ptr);
    if (stack->current_shape.IsNull()) return false;

    // 書き出し倍率。STEP 側の単位は MM のままで、**形状を拡大縮小する**。
    //
    // `write.step.unit` をいじる手もあるが、あれは「同じ大きさに別の単位名を
    // 付ける」だけで、物理的な寸法は変わらない。ここで要るのは「1 Blender
    // 単位を何 mm として出すか」なので、形状側を掛ける。インポートが
    // import_step の safe_scale で行っているのと同じ扱いに揃えてある。
    const double safe_scale = std::max(scale, 1e-6);
    TopoDS_Shape out_shape = stack->current_shape;
    if (std::abs(safe_scale - 1.0) > 1e-9) {
        try {
            gp_GTrsf gt_scale;
            gt_scale.SetVectorialPart(gp_Mat(
                safe_scale, 0, 0,
                0, safe_scale, 0,
                0, 0, safe_scale
            ));
            out_shape = BRepBuilderAPI_GTransform(stack->current_shape, gt_scale, true).Shape();
        } catch (...) {
            occ_core::log_debug("export_stack_to_step: scaling failed; writing at 1:1");
            out_shape = stack->current_shape;
        }
    }
    if (out_shape.IsNull()) return false;

    STEPControl_Writer writer;
    Interface_Static::SetIVal("write.step.schema", 4);
    writer.Transfer(out_shape, STEPControl_AsIs);
    IFSelect_ReturnStatus status = writer.Write(filepath.c_str());
    return status == IFSelect_RetDone;
}

/// 書き出し倍率をかけた形状を返す。かけない場合は元の形状をそのまま返す
/// (STEP は B-Rep を書くので、三角形分割の有無は結果に影響しない)。
///
/// export_stack_to_step / export_stack_to_stl にも同じ処理が書かれているが、
/// あちらは本関数より先にあったもの。触るときに寄せること。
static TopoDS_Shape scaled_for_export(const TopoDS_Shape& shape, double safe_scale,
                                      const char* tag) {
    if (shape.IsNull() || std::abs(safe_scale - 1.0) <= 1e-9) return shape;
    try {
        gp_GTrsf gt_scale;
        gt_scale.SetVectorialPart(gp_Mat(
            safe_scale, 0, 0,
            0, safe_scale, 0,
            0, 0, safe_scale
        ));
        return BRepBuilderAPI_GTransform(shape, gt_scale, true).Shape();
    } catch (...) {
        occ_core::log_debug(std::string(tag) + ": scaling failed; writing at 1:1");
        return shape;
    }
}

/// ソリッド1個だけを包んでいるコンパウンドなら、中身のソリッドを返す。
///
/// スタックの結果はコンパウンドで返ることがある。それをそのまま XCAF の
/// アセンブリに入れると、`PRODUCT('PartA')` の下に無名の `PRODUCT('SOLID')`
/// がもう一段ぶら下がり、受け取った側のツリーに意味のない階層が増える
/// (実際に最初の実装がそうなっていた)。
///
/// **子が2つ以上あるときは触らない。** 中身が複数のソリッドなら、それは
/// 本当に部品が複数あるということなので、階層は正しい。
static TopoDS_Shape unwrap_lone_solid(const TopoDS_Shape& shape) {
    if (shape.IsNull() || shape.ShapeType() != TopAbs_COMPOUND) return shape;
    TopoDS_Iterator it(shape);
    if (!it.More()) return shape;
    TopoDS_Shape first = it.Value();
    it.Next();
    if (it.More()) return shape;                       // 子が2つ以上
    if (first.ShapeType() != TopAbs_SOLID) return shape;
    return first;
}

/// XCAF のラベルに名前を付ける。
///
/// **UTF-8 として解釈させること** (第2引数 Standard_True)。Blender の
/// コレクション名には日本語が入りうるので、既定の Standard_False で渡すと
/// 各バイトが1文字として扱われ、STEP 側で文字化けする。
static void set_label_name(const TDF_Label& label, const std::string& name) {
    if (label.IsNull() || name.empty()) return;
    TDataStd_Name::Set(label, TCollection_ExtendedString(name.c_str(), Standard_True));
}

bool export_parts_to_step(const std::vector<void*>& stack_ptrs,
                          const std::vector<std::string>& names,
                          const std::string& filepath,
                          double scale,
                          const std::string& assembly_name) {
    if (stack_ptrs.empty() || stack_ptrs.size() != names.size()) {
        occ_core::log_debug("export_parts_to_step: no parts, or names do not match parts");
        return false;
    }

    const double safe_scale = std::max(scale, 1e-6);

    // 形が無いスタックは黙って読み飛ばす。Part を作っただけでまだ何も置いて
    // いない、という状態は普通に起こる。全部空なら失敗として返す。
    std::vector<TopoDS_Shape> shapes;
    std::vector<std::string> kept_names;
    for (size_t i = 0; i < stack_ptrs.size(); ++i) {
        if (!stack_ptrs[i]) continue;
        occ_core::CADStack* stack = static_cast<occ_core::CADStack*>(stack_ptrs[i]);
        if (stack->current_shape.IsNull()) {
            occ_core::log_debug("export_parts_to_step: skipping empty part '" + names[i] + "'");
            continue;
        }
        TopoDS_Shape s = scaled_for_export(stack->current_shape, safe_scale, "export_parts_to_step");
        s = unwrap_lone_solid(s);
        if (s.IsNull()) continue;
        shapes.push_back(s);
        kept_names.push_back(names[i]);
    }
    if (shapes.empty()) {
        occ_core::log_debug("export_parts_to_step: every part was empty; nothing to write");
        return false;
    }

    try {
        OCC_CATCH_SIGNALS

        // "MDTV-XCAF" はメモリ上の XCAF 文書の従来フォーマット名。保存しない
        // 限りストレージドライバは要らないので、TKBinXCAF をリンクせずに済む。
        Handle(TDocStd_Document) doc;
        Handle(XCAFApp_Application) app = XCAFApp_Application::GetApplication();
        app->NewDocument("MDTV-XCAF", doc);
        if (doc.IsNull()) {
            occ_core::log_debug("export_parts_to_step: could not create an XCAF document");
            return false;
        }
        Handle(XCAFDoc_ShapeTool) shape_tool = XCAFDoc_DocumentTool::ShapeTool(doc->Main());

        if (shapes.size() == 1) {
            // 1つだけのときにアセンブリを作ると、部品が1個ぶら下がっただけの
            // 入れ子が出来て読み手に無駄な階層を見せる。素直に名前付きの
            // 単独形状として出す。
            TDF_Label lab = shape_tool->AddShape(shapes[0], Standard_False);
            set_label_name(lab, kept_names[0]);
        } else {
            TopoDS_Compound compound;
            BRep_Builder builder;
            builder.MakeCompound(compound);
            for (const auto& s : shapes) builder.Add(compound, s);

            // makeAssembly = true。コンパウンドの子が構成要素になる。
            TDF_Label asm_lab = shape_tool->AddShape(compound, Standard_True);
            set_label_name(asm_lab, assembly_name);

            // 構成要素は**参照**で、名前は参照先(プロトタイプ)に付けないと
            // STEP の PRODUCT 名にならない。両方に付けておく。
            TDF_LabelSequence components;
            shape_tool->GetComponents(asm_lab, components);
            if (components.Length() != static_cast<Standard_Integer>(kept_names.size())) {
                // 同一形状の Part が複数あるとプロトタイプが共有され、
                // 構成要素の数と名前の数がずれることがある。名前を取り違えて
                // 付けるくらいなら、付けずに形状だけ出すほうがまし。
                occ_core::log_debug("export_parts_to_step: component count " +
                                    std::to_string(components.Length()) + " != name count " +
                                    std::to_string(kept_names.size()) + "; writing without part names");
            } else {
                for (Standard_Integer i = 1; i <= components.Length(); ++i) {
                    const TDF_Label& comp_lab = components.Value(i);
                    set_label_name(comp_lab, kept_names[i - 1]);
                    TDF_Label ref_lab;
                    if (shape_tool->GetReferredShape(comp_lab, ref_lab)) {
                        set_label_name(ref_lab, kept_names[i - 1]);
                    }
                }
            }
        }

        STEPCAFControl_Writer writer;
        writer.SetNameMode(Standard_True);
        Interface_Static::SetIVal("write.step.schema", 4);
        if (!writer.Transfer(doc, STEPControl_AsIs)) {
            occ_core::log_debug("export_parts_to_step: XCAF transfer failed");
            return false;
        }
        IFSelect_ReturnStatus status = writer.Write(filepath.c_str());
        if (status != IFSelect_RetDone) {
            occ_core::log_debug("export_parts_to_step: failed to write " + filepath);
            return false;
        }
        occ_core::log_debug("export_parts_to_step: wrote " + std::to_string(shapes.size()) +
                            " named part(s) to " + filepath);
        return true;

    } catch (Standard_Failure const& e) {
        occ_core::log_debug(std::string("export_parts_to_step: ") + e.GetMessageString());
        return false;
    } catch (...) {
        occ_core::log_debug("export_parts_to_step: unknown exception");
        return false;
    }
}

bool export_stack_to_stl(void* stack_ptr, const std::string& filepath, double scale,
                         double linear_deflection, double angular_deflection,
                         bool ascii_mode) {
    if (!stack_ptr) return false;
    occ_core::CADStack* stack = static_cast<occ_core::CADStack*>(stack_ptr);
    if (stack->current_shape.IsNull()) return false;

    // 倍率の扱いは export_stack_to_step と同一。STL には単位の概念が無いので、
    // 「1 Blender 単位を何 mm として出すか」は形状を掛けるしかない。
    //
    // **必ずコピーを作ること。** 下で三角形分割を捨てるので、生の
    // current_shape を渡すと**プレビューの描画用メッシュを壊す**。
    const double safe_scale = std::max(scale, 1e-6);
    TopoDS_Shape out_shape;
    try {
        if (std::abs(safe_scale - 1.0) > 1e-9) {
            gp_GTrsf gt_scale;
            gt_scale.SetVectorialPart(gp_Mat(
                safe_scale, 0, 0,
                0, safe_scale, 0,
                0, 0, safe_scale
            ));
            out_shape = BRepBuilderAPI_GTransform(stack->current_shape, gt_scale, true).Shape();
        } else {
            // 等倍でもコピーする。ここを「そのまま使う」にすると、等倍のときだけ
            // 生の形状を掴むことになり、Clean がプレビューを巻き込む。
            out_shape = BRepBuilderAPI_Copy(stack->current_shape).Shape();
        }
    } catch (...) {
        occ_core::log_debug("export_stack_to_stl: could not copy the shape");
        return false;
    }
    if (out_shape.IsNull()) return false;

    // **既存の三角形分割を必ず捨ててから切り直す。**
    //
    // BRepMesh_IncrementalMesh は「既にあるメッシュが要求精度を満たしていれば
    // その面を作り直さない」。current_shape にはプレビューが作った分割が載って
    // いるので、Clean しないと**指定した品質が黙って無視され、画面用の粗さで
    // STL が出る**。Bake 経路を通さない利点そのものが消える。
    //
    // 2026-08-17 のサボタージュ検証で発覚した。メッシュ生成を丸ごと削っても
    // テストが緑のままで、それは三角形がプレビュー由来だったため。
    BRepTools::Clean(out_shape);

    // たわみ量にも同じ倍率を掛ける。scale を変えてもメッシュの相対的な粗さは
    // 変わらない (10倍で出したから10倍粗くなる、ということが起きない)。
    //
    // angular_deflection は**ラジアン**で受ける。UI 側は度で持っているので、
    // 変換は呼び出し側の責任。ベイク経路 (operators/bake.py) と同じ約束。
    const double lin = std::max(linear_deflection, 1e-6) * safe_scale;
    const double ang = std::max(angular_deflection, 1e-6);
    try {
        OCC_CATCH_SIGNALS
        BRepMesh_IncrementalMesh mesh(out_shape, lin, Standard_False, ang, Standard_True);
        (void)mesh;
    } catch (Standard_Failure const& e) {
        occ_core::log_debug(std::string("export_stack_to_stl: meshing failed: ") + e.GetMessageString());
        return false;
    } catch (...) {
        occ_core::log_debug("export_stack_to_stl: meshing failed (unknown exception)");
        return false;
    }

    // 三角形が1枚も無いまま書くと、**開けるが中身が空**の STL ができる。
    // 一番たちの悪い失敗方なので、書く前に落とす。StlAPI_Writer は
    // 自分でメッシュを切らないため、この確認をしないと静かに空になる。
    int n_triangles = 0;
    for (TopExp_Explorer exp(out_shape, TopAbs_FACE); exp.More(); exp.Next()) {
        TopLoc_Location loc;
        Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(TopoDS::Face(exp.Current()), loc);
        if (!tri.IsNull()) n_triangles += tri->NbTriangles();
    }
    if (n_triangles == 0) {
        occ_core::log_debug("export_stack_to_stl: no triangles after meshing; refusing to write an empty file");
        return false;
    }

    StlAPI_Writer writer;
    writer.ASCIIMode() = ascii_mode ? Standard_True : Standard_False;
    const bool ok = writer.Write(out_shape, filepath.c_str()) == Standard_True;
    if (!ok) {
        occ_core::log_debug("export_stack_to_stl: StlAPI_Writer failed for " + filepath);
    } else {
        occ_core::log_debug("export_stack_to_stl: wrote " + std::to_string(n_triangles) +
                            " triangles to " + filepath);
    }
    return ok;
}

} // namespace occ
