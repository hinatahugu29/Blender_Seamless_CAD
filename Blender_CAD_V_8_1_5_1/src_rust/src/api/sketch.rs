pub fn solve_sketch(

    points: Vec<(u32, f64, f64)>, // (id, x, y)

    constraints: Vec<(String, Vec<u32>, f64)> // (type, target_ids, value)

) -> Result<Vec<(u32, f64, f64)>, String> {

    use ezpz::{solve, Config, Constraint, ConstraintRequest, IdGenerator};

    use ezpz::datatypes::inputs::{DatumPoint, DatumLineSegment, DatumCircularArc, DatumCircle, DatumDistance};

    use std::collections::HashMap;



    // 1. 各頂点の DatumPoint を構築し、初期推定値をマッピング

    let mut ids = IdGenerator::default();

    let mut point_map = HashMap::new();

    let mut initial_guesses = Vec::new();



    // ezpzの変数IDと元々の点ID/座標軸のマッピングを保持する

    // solveから返ってくるoutcomeのfinal_valuesは「初期推定値リストと同じ順序」で解決後の値が入っている。

    // そのため、順序を追跡できるようにする。

    let mut guess_index_to_point_axis = Vec::new(); // (p_id, is_y)



    for &(p_id, x, y) in &points {

        let p = DatumPoint::new(&mut ids);

        

        initial_guesses.push((p.id_x(), x));

        guess_index_to_point_axis.push((p_id, false)); // x axis

        

        initial_guesses.push((p.id_y(), y));

        guess_index_to_point_axis.push((p_id, true));  // y axis

        

        point_map.insert(p_id, p);

    }



    // 2. 拘束リスト（Request）を組み立てる

    let mut requests = Vec::new();



    for (c_type, targets, value) in &constraints {

        match c_type.as_str() {

            "FIXED" => {

                if let Some(&p_id) = targets.first() {

                    if let Some(p) = point_map.get(&p_id) {

                        // 点のXとYの現在座標を取得

                        if let Some(&(_, x, y)) = points.iter().find(|(id, _, _)| *id == p_id) {

                            requests.push(ConstraintRequest::highest_priority(Constraint::Fixed(p.id_x(), x)));

                            requests.push(ConstraintRequest::highest_priority(Constraint::Fixed(p.id_y(), y)));

                        }

                    }

                }

            }

            "DISTANCE" => {

                if targets.len() >= 2 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    if let (Some(p1), Some(p2)) = (point_map.get(&p1_id), point_map.get(&p2_id)) {

                        requests.push(ConstraintRequest::highest_priority(Constraint::Distance(*p1, *p2, *value)));

                    }

                }

            }

            // 円・円弧の半径を数値で固定する。targets = [中心点, 円周上の点]。
            //
            // ezpz の CircleRadius は「半径変数だけ」を式に出す (constraints.rs の
            // all_variables を参照)。つまり半径変数を作って固定しただけでは、その
            // 変数はどの点にも繋がっておらず形状は動かない。DistanceVar で
            // 中心と円周上の点の距離をその変数に縛って初めて効く。
            // TANGENT が円を組み立てているのと同じ手順。
            //
            // Distance(中心, 円周点, value) 一本でも数値上は同じ結果になるが、
            // それだと DISTANCE と実装が区別できなくなる。半径として書く。
            "RADIUS" => {

                if targets.len() >= 2 {

                    let c_id = targets[0];

                    let rim_id = targets[1];

                    if let (Some(c), Some(rim)) = (point_map.get(&c_id), point_map.get(&rim_id)) {

                        let r = DatumDistance::new(ids.next_id());

                        // 初期推定値は現在の半径。ここを value にすると、拘束を
                        // 付けた瞬間に解が遠くへ飛んでスケッチが暴れる。
                        let mut r_val = *value;

                        if let (Some(&(_, cx, cy)), Some(&(_, rx, ry))) = (

                            points.iter().find(|(id, _, _)| *id == c_id),

                            points.iter().find(|(id, _, _)| *id == rim_id),

                        ) {

                            let (dx, dy) = (rx - cx, ry - cy);

                            r_val = (dx * dx + dy * dy).sqrt();

                        }

                        initial_guesses.push((r.id, r_val));

                        let circle = DatumCircle { center: *c, radius: r };

                        requests.push(ConstraintRequest::highest_priority(Constraint::CircleRadius(circle, *value)));

                        requests.push(ConstraintRequest::highest_priority(Constraint::DistanceVar(*c, *rim, r)));

                    }

                }

            }

            "HORIZONTAL" => {

                if targets.len() >= 2 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    if let (Some(p1), Some(p2)) = (point_map.get(&p1_id), point_map.get(&p2_id)) {

                        let line = DatumLineSegment { p0: *p1, p1: *p2 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::Horizontal(line)));

                    }

                }

            }

            "MIDPOINT" => {

                if targets.len() >= 3 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    let pm_id = targets[2];

                    if let (Some(p1), Some(p2), Some(pm)) = (point_map.get(&p1_id), point_map.get(&p2_id), point_map.get(&pm_id)) {

                        let line = DatumLineSegment { p0: *p1, p1: *p2 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::Midpoint(line, *pm)));

                    }

                }

            }

            "ARC" => {

                if targets.len() >= 4 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    let p3_id = targets[2];

                    let c_id = targets[3];

                    if let (Some(p1), Some(p2), Some(p3), Some(c)) = (

                        point_map.get(&p1_id),

                        point_map.get(&p2_id),

                        point_map.get(&p3_id),

                        point_map.get(&c_id),

                    ) {

                        let arc12 = DatumCircularArc { center: *c, start: *p1, end: *p2 };

                        let arc13 = DatumCircularArc { center: *c, start: *p1, end: *p3 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::Arc(arc12)));

                        requests.push(ConstraintRequest::highest_priority(Constraint::Arc(arc13)));

                    }

                }

            }

            "VERTICAL" => {

                if targets.len() >= 2 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    if let (Some(p1), Some(p2)) = (point_map.get(&p1_id), point_map.get(&p2_id)) {

                        let line = DatumLineSegment { p0: *p1, p1: *p2 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::Vertical(line)));

                    }

                }

            }

            // 同心。targets = [円1の中心, 円2の中心]。
            //
            // Coincident(点の統合)とは別物であることに注意。あちらは点IDを
            // 付け替えて片方を消す破壊的な編集で、元に戻せない。こちらは
            // 2つの中心点を別々の点のまま残し、位置だけ一致させる拘束。
            "CONCENTRIC" => {

                if targets.len() >= 2 {

                    if let (Some(p1), Some(p2)) = (point_map.get(&targets[0]), point_map.get(&targets[1])) {

                        requests.push(ConstraintRequest::highest_priority(Constraint::PointsCoincident(*p1, *p2)));

                    }

                }

            }

            // 対称。targets = [軸の始点, 軸の終点, 点1, 点2]。
            // ezpz の引数順は (線, 点, 点) なので、targets の並びとは違う。
            "SYMMETRIC" => {

                if targets.len() >= 4 {

                    if let (Some(a1), Some(a2), Some(p1), Some(p2)) = (

                        point_map.get(&targets[0]),

                        point_map.get(&targets[1]),

                        point_map.get(&targets[2]),

                        point_map.get(&targets[3]),

                    ) {

                        let axis = DatumLineSegment { p0: *a1, p1: *a2 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::Symmetric(axis, *p1, *p2)));

                    }

                }

            }

            // 2本の線がなす角を数値で固定する。targets = [線1始点, 線1終点, 線2始点, 線2終点]、
            // value は **度**。PARALLEL / PERPENDICULAR と同じ並びなので、
            // 選択の解釈は Python 側でそのまま使い回せる。
            //
            // RADIUS と違い、LinesAtAngle は両方の線の全変数を式に出す
            // (constraints.rs の all_variables)。点に直接繋がっているので
            // DistanceVar のような橋渡しは要らない。
            "ANGLE" => {

                if targets.len() >= 4 {

                    if let (Some(p1), Some(p2), Some(p3), Some(p4)) = (

                        point_map.get(&targets[0]),

                        point_map.get(&targets[1]),

                        point_map.get(&targets[2]),

                        point_map.get(&targets[3]),

                    ) {

                        let l1 = DatumLineSegment { p0: *p1, p1: *p2 };

                        let l2 = DatumLineSegment { p0: *p3, p1: *p4 };

                        let angle = ezpz::datatypes::AngleKind::Other(

                            ezpz::datatypes::Angle::from_degrees(*value)

                        );

                        requests.push(ConstraintRequest::highest_priority(Constraint::LinesAtAngle(l1, l2, angle)));

                    }

                }

            }

            // 2本の線の長さを揃える。targets は ANGLE と同じ並び。value は使わない。
            "EQUAL" => {

                if targets.len() >= 4 {

                    if let (Some(p1), Some(p2), Some(p3), Some(p4)) = (

                        point_map.get(&targets[0]),

                        point_map.get(&targets[1]),

                        point_map.get(&targets[2]),

                        point_map.get(&targets[3]),

                    ) {

                        let l1 = DatumLineSegment { p0: *p1, p1: *p2 };

                        let l2 = DatumLineSegment { p0: *p3, p1: *p4 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::LinesEqualLength(l1, l2)));

                    }

                }

            }

            "PARALLEL" => {

                if targets.len() >= 4 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    let p3_id = targets[2];

                    let p4_id = targets[3];

                    if let (Some(p1), Some(p2), Some(p3), Some(p4)) = (

                        point_map.get(&p1_id),

                        point_map.get(&p2_id),

                        point_map.get(&p3_id),

                        point_map.get(&p4_id),

                    ) {

                        let l1 = DatumLineSegment { p0: *p1, p1: *p2 };

                        let l2 = DatumLineSegment { p0: *p3, p1: *p4 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::lines_parallel([l1, l2])));

                    }

                }

            }

            "PERPENDICULAR" => {

                if targets.len() >= 4 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    let p3_id = targets[2];

                    let p4_id = targets[3];

                    if let (Some(p1), Some(p2), Some(p3), Some(p4)) = (

                        point_map.get(&p1_id),

                        point_map.get(&p2_id),

                        point_map.get(&p3_id),

                        point_map.get(&p4_id),

                    ) {

                        let l1 = DatumLineSegment { p0: *p1, p1: *p2 };

                        let l2 = DatumLineSegment { p0: *p3, p1: *p4 };

                        requests.push(ConstraintRequest::highest_priority(Constraint::lines_perpendicular([l1, l2])));

                    }

                }

            }

            "TANGENT" => {

                let get_pt_val = |p_id: u32| -> Option<(f64, f64)> {

                    points.iter().find(|(id, _, _)| *id == p_id).map(|(_, x, y)| (*x, *y))

                };

                

                if targets.len() == 4 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    let c_id = targets[2];

                    let pr_id = targets[3];

                    if let (Some(p1), Some(p2), Some(c), Some(pr)) = (

                        point_map.get(&p1_id),

                        point_map.get(&p2_id),

                        point_map.get(&c_id),

                        point_map.get(&pr_id),

                    ) {

                        let line_seg = DatumLineSegment { p0: *p1, p1: *p2 };

                        let r = DatumDistance::new(ids.next_id());

                        

                        let mut r_val = 1.0;

                        if let (Some(c_val), Some(pr_val)) = (get_pt_val(c_id), get_pt_val(pr_id)) {

                            let dx = pr_val.0 - c_val.0;

                            let dy = pr_val.1 - c_val.1;

                            r_val = (dx*dx + dy*dy).sqrt();

                        }

                        

                        initial_guesses.push((r.id, r_val));

                        

                        let circle = DatumCircle { center: *c, radius: r };

                        

                        requests.push(ConstraintRequest::highest_priority(Constraint::LineTangentToCircle(

                            line_seg,

                            circle,

                            ezpz::LineSide::Undefined

                        )));

                        requests.push(ConstraintRequest::highest_priority(Constraint::DistanceVar(

                            *c,

                            *pr,

                            r

                        )));

                    }

                } else if targets.len() == 5 {

                    let p1_id = targets[0];

                    let p2_id = targets[1];

                    let s_id = targets[2];

                    let e_id = targets[3];

                    let m_id = targets[4];

                    if let (Some(p1), Some(p2), Some(s), Some(e), Some(m)) = (

                        point_map.get(&p1_id),

                        point_map.get(&p2_id),

                        point_map.get(&s_id),

                        point_map.get(&e_id),

                        point_map.get(&m_id),

                    ) {

                        let line_seg = DatumLineSegment { p0: *p1, p1: *p2 };

                        

                        let c = DatumPoint::new(&mut ids);

                        let r = DatumDistance::new(ids.next_id());

                        

                        let mut xc = 0.0;

                        let mut yc = 0.0;

                        let mut r_val = 1.0;

                        

                        if let (Some(s_val), Some(e_val), Some(m_val)) = (

                            get_pt_val(s_id),

                            get_pt_val(e_id),

                            get_pt_val(m_id)

                        ) {

                            let (x1, y1) = s_val;

                            let (x2, y2) = e_val;

                            let (x3, y3) = m_val;

                            

                            let d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2));

                            if d.abs() > 1e-6 {

                                xc = ((x1*x1 + y1*y1) * (y2 - y3) + (x2*x2 + y2*y2) * (y3 - y1) + (x3*x3 + y3*y3) * (y1 - y2)) / d;

                                yc = ((x1*x1 + y1*y1) * (x3 - x2) + (x2*x2 + y2*y2) * (x1 - x3) + (x3*x3 + y3*y3) * (x2 - x1)) / d;

                                r_val = ((x1 - xc)*(x1 - xc) + (y1 - yc)*(y1 - yc)).sqrt();

                            } else {

                                xc = (x1 + x2) * 0.5;

                                yc = (y1 + y2) * 0.5;

                                r_val = ((x1 - xc)*(x1 - xc) + (y1 - yc)*(y1 - yc)).sqrt();

                            }

                        }

                        

                        initial_guesses.push((c.id_x(), xc));

                        initial_guesses.push((c.id_y(), yc));

                        initial_guesses.push((r.id, r_val));

                        

                        let arc = DatumCircularArc { center: c, start: *s, end: *e };

                        let circle = DatumCircle { center: c, radius: r };

                        

                        requests.push(ConstraintRequest::highest_priority(Constraint::Arc(arc)));

                        requests.push(ConstraintRequest::highest_priority(Constraint::DistanceVar(

                            c,

                            *m,

                            r

                        )));

                        requests.push(ConstraintRequest::highest_priority(Constraint::DistanceVar(

                            c,

                            *s,

                            r

                        )));

                        requests.push(ConstraintRequest::highest_priority(Constraint::LineTangentToCircle(

                            line_seg,

                            circle,

                            ezpz::LineSide::Undefined

                        )));

                    }

                }

            }

            _ => {

                println!("Seamless CAD: Warning - Unsupported constraint type: {}", c_type);

            }

        }

    }



    // 3. ソルバー実行！

    match solve(&requests, initial_guesses, Config::default()) {

        Ok(outcome) => {

            let final_values = outcome.final_values();

            

            // 各点IDごとの新しい座標を再構築する

            let mut resolved_coords: HashMap<u32, (f64, f64)> = HashMap::new();

            for &(p_id, _, _) in &points {

                resolved_coords.insert(p_id, (0.0, 0.0));

            }



            for (idx, &val) in final_values.iter().enumerate() {

                if idx < guess_index_to_point_axis.len() {

                    let (p_id, is_y) = guess_index_to_point_axis[idx];

                    if let Some(coord) = resolved_coords.get_mut(&p_id) {

                        if is_y {

                            coord.1 = val;

                        } else {

                            coord.0 = val;

                        }

                    }

                }

            }



            // 元の入力と同じ順序で結果のリストを作成して返却する

            let mut result = Vec::new();

            for &(p_id, _, _) in &points {

                if let Some(&(x, y)) = resolved_coords.get(&p_id) {

                    result.push((p_id, x, y));

                }

            }



            Ok(result)

        }

        Err(e) => {

            Err(String::from(format!(

                "幾何拘束の解決に失敗しました。過拘束または矛盾がある可能性があります: {:?}",

                e.error

            )))

        }

    }

}

