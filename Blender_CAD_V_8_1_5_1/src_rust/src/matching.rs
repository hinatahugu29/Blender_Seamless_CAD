//! Maximum-weight matching in a general graph (Edmonds' blossom algorithm,
//! primal-dual, O(n^3)), for Quad Bake's triangle pairing. Integer weights;
//! they are doubled inside so every dual variable stays an integer.
//!
//! Written for this project from the textbook formulation (Galil, "Efficient
//! algorithms for finding maximum matching in graphs", 1986), following the
//! same stage / substage structure as the well-known reference
//! implementations. Returns mate[v] = partner vertex or -1.

pub fn max_weight_matching(nvertex: usize, edges_in: &[(usize, usize, i64)]) -> Vec<i64> {
    let edges: Vec<(usize, usize, i64)> = edges_in
        .iter()
        .filter(|e| e.0 != e.1 && e.0 < nvertex && e.1 < nvertex)
        .map(|&(i, j, w)| (i, j, 2 * w))
        .collect();
    let nedge = edges.len();
    let mut mate_out = vec![-1i64; nvertex];
    if nedge == 0 || nvertex == 0 {
        return mate_out;
    }
    let maxweight = edges.iter().map(|e| e.2).max().unwrap_or(0).max(0);
    // endpoint p: vertex at end p of edge p/2
    let endpoint: Vec<usize> = (0..2 * nedge).map(|p| if p % 2 == 0 { edges[p / 2].0 } else { edges[p / 2].1 }).collect();
    let mut neighbend: Vec<Vec<usize>> = vec![Vec::new(); nvertex];
    for (k, &(i, j, _)) in edges.iter().enumerate() {
        neighbend[i].push(2 * k + 1);
        neighbend[j].push(2 * k);
    }
    const NONE: i64 = -1;
    let n2 = 2 * nvertex;
    let mut mate: Vec<i64> = vec![NONE; nvertex]; // remote endpoint
    let mut label: Vec<u8> = vec![0; n2];
    let mut labelend: Vec<i64> = vec![NONE; n2];
    let mut inblossom: Vec<usize> = (0..nvertex).collect();
    let mut blossomparent: Vec<i64> = vec![NONE; n2];
    let mut blossomchilds: Vec<Vec<usize>> = vec![Vec::new(); n2];
    let mut blossombase: Vec<i64> = (0..nvertex as i64).chain(std::iter::repeat(NONE).take(nvertex)).collect();
    let mut blossomendps: Vec<Vec<usize>> = vec![Vec::new(); n2];
    let mut bestedge: Vec<i64> = vec![NONE; n2];
    let mut blossombestedges: Vec<Option<Vec<usize>>> = vec![None; n2];
    let mut unusedblossoms: Vec<usize> = (nvertex..n2).collect();
    let mut dualvar: Vec<i64> = (0..n2).map(|i| if i < nvertex { maxweight } else { 0 }).collect();
    let mut allowedge: Vec<bool> = vec![false; nedge];
    let mut queue: Vec<usize> = Vec::new();

    macro_rules! slack {
        ($k:expr) => {{
            let (i, j, w) = edges[$k];
            dualvar[i] + dualvar[j] - 2 * w
        }};
    }

    fn leaves(b: usize, nvertex: usize, childs: &Vec<Vec<usize>>, out: &mut Vec<usize>) {
        if b < nvertex {
            out.push(b);
        } else {
            for &t in &childs[b] {
                leaves(t, nvertex, childs, out);
            }
        }
    }

    // the whole algorithm works on these closures-turned-loops; helpers below
    // take explicit state to keep the borrow checker satisfied
    struct St<'a> {
        nvertex: usize,
        edges: &'a Vec<(usize, usize, i64)>,
        endpoint: &'a Vec<usize>,
        neighbend: &'a Vec<Vec<usize>>,
    }
    let st = St { nvertex, edges: &edges, endpoint: &endpoint, neighbend: &neighbend };

    for _stage in 0..nvertex {
        for x in label.iter_mut() {
            *x = 0;
        }
        for x in bestedge.iter_mut() {
            *x = NONE;
        }
        for b in nvertex..n2 {
            blossombestedges[b] = None;
        }
        for x in allowedge.iter_mut() {
            *x = false;
        }
        queue.clear();
        // label single free vertices S
        for v in 0..nvertex {
            if mate[v] == NONE && label[inblossom[v]] == 0 {
                assign_label(v, 1, NONE, &st, &mut label, &mut labelend, &inblossom, &mut bestedge, &mut queue,
                             &blossomchilds, &blossombase, &mate);
            }
        }
        let mut augmented = false;
        loop {
            while let Some(v) = queue.pop() {
                debug_assert!(label[inblossom[v]] == 1);
                let mut k_i = 0;
                while k_i < st.neighbend[v].len() {
                    let p = st.neighbend[v][k_i];
                    k_i += 1;
                    let k = p / 2;
                    let w = st.endpoint[p];
                    if inblossom[v] == inblossom[w] {
                        continue;
                    }
                    let mut kslack = 0;
                    if !allowedge[k] {
                        kslack = slack!(k);
                        if kslack <= 0 {
                            allowedge[k] = true;
                        }
                    }
                    if allowedge[k] {
                        if label[inblossom[w]] == 0 {
                            assign_label(w, 2, (p ^ 1) as i64, &st, &mut label, &mut labelend, &inblossom,
                                         &mut bestedge, &mut queue, &blossomchilds, &blossombase, &mate);
                        } else if label[inblossom[w]] == 1 {
                            let base = scan_blossom(v, w, &st, &mut label, &labelend, &inblossom, &blossomparent,
                                                    &blossombase, &mate);
                            if base >= 0 {
                                add_blossom(base as usize, k, &st, &mut label, &mut labelend, &mut inblossom,
                                            &mut blossomparent, &mut blossomchilds, &mut blossombase,
                                            &mut blossomendps, &mut bestedge, &mut blossombestedges,
                                            &mut unusedblossoms, &mut dualvar, &mut queue, &mate);
                            } else {
                                augment_matching(k, &st, &mut mate, &labelend, &inblossom, &blossomparent,
                                                 &mut blossomchilds, &mut blossombase, &mut blossomendps, &label);
                                augmented = true;
                                break;
                            }
                        } else if label[w] == 0 {
                            label[w] = 2;
                            labelend[w] = (p ^ 1) as i64;
                        }
                    } else if label[inblossom[w]] == 1 {
                        let b = inblossom[v];
                        if bestedge[b] == NONE || kslack < slack!(bestedge[b] as usize) {
                            bestedge[b] = k as i64;
                        }
                    } else if label[w] == 0 {
                        if bestedge[w] == NONE || kslack < slack!(bestedge[w] as usize) {
                            bestedge[w] = k as i64;
                        }
                    }
                }
                if augmented {
                    break;
                }
            }
            if augmented {
                break;
            }
            // no augmenting path: compute delta
            let mut deltatype = -1i32;
            let mut delta = 0i64;
            let mut deltaedge = NONE;
            let mut deltablossom = NONE;
            // type 1: minimum dual of a vertex (max-weight, not max-cardinality)
            deltatype = 1;
            delta = *dualvar[..nvertex].iter().min().unwrap();
            // type 2
            for v in 0..nvertex {
                if label[inblossom[v]] == 0 && bestedge[v] != NONE {
                    let d = slack!(bestedge[v] as usize);
                    if deltatype == -1 || d < delta {
                        delta = d;
                        deltatype = 2;
                        deltaedge = bestedge[v];
                    }
                }
            }
            // type 3
            for b in 0..n2 {
                if blossomparent[b] == NONE && label[b] == 1 && bestedge[b] != NONE {
                    let kslack = slack!(bestedge[b] as usize);
                    debug_assert!(kslack % 2 == 0);
                    let d = kslack / 2;
                    if deltatype == -1 || d < delta {
                        delta = d;
                        deltatype = 3;
                        deltaedge = bestedge[b];
                    }
                }
            }
            // type 4
            for b in nvertex..n2 {
                if blossombase[b] >= 0 && blossomparent[b] == NONE && label[b] == 2
                    && (deltatype == -1 || dualvar[b] < delta) {
                    delta = dualvar[b];
                    deltatype = 4;
                    deltablossom = b as i64;
                }
            }
            if deltatype == -1 {
                deltatype = 1;
                delta = (*dualvar[..nvertex].iter().min().unwrap()).max(0);
            }
            // update duals
            for v in 0..nvertex {
                match label[inblossom[v]] {
                    1 => dualvar[v] -= delta,
                    2 => dualvar[v] += delta,
                    _ => {}
                }
            }
            for b in nvertex..n2 {
                if blossombase[b] >= 0 && blossomparent[b] == NONE {
                    match label[b] {
                        1 => dualvar[b] += delta,
                        2 => dualvar[b] -= delta,
                        _ => {}
                    }
                }
            }
            match deltatype {
                1 => break,
                2 => {
                    let k = deltaedge as usize;
                    allowedge[k] = true;
                    let (mut i, j, _) = edges[k];
                    if label[inblossom[i]] == 0 {
                        i = j;
                    }
                    debug_assert!(label[inblossom[i]] == 1);
                    queue.push(i);
                }
                3 => {
                    let k = deltaedge as usize;
                    allowedge[k] = true;
                    let (i, _, _) = edges[k];
                    debug_assert!(label[inblossom[i]] == 1);
                    queue.push(i);
                }
                4 => {
                    expand_blossom(deltablossom as usize, false, &st, &mut label, &mut labelend, &mut inblossom,
                                   &mut blossomparent, &mut blossomchilds, &mut blossombase, &mut blossomendps,
                                   &mut bestedge, &mut blossombestedges, &mut unusedblossoms, &mut dualvar,
                                   &mut allowedge, &mut queue, &mate);
                }
                _ => {}
            }
        }
        if !augmented {
            break;
        }
        // end of stage: expand S-blossoms with zero dual
        for b in nvertex..n2 {
            if blossomparent[b] == NONE && blossombase[b] >= 0 && label[b] == 1 && dualvar[b] == 0 {
                expand_blossom(b, true, &st, &mut label, &mut labelend, &mut inblossom, &mut blossomparent,
                               &mut blossomchilds, &mut blossombase, &mut blossomendps, &mut bestedge,
                               &mut blossombestedges, &mut unusedblossoms, &mut dualvar, &mut allowedge,
                               &mut queue, &mate);
            }
        }
    }
    for v in 0..nvertex {
        if mate[v] >= 0 {
            mate_out[v] = endpoint[mate[v] as usize] as i64;
        }
    }
    let _ = leaves;
    return mate_out;

    // ---------------------------------------------------------------------
    fn blossom_leaves(b: usize, nvertex: usize, childs: &Vec<Vec<usize>>) -> Vec<usize> {
        let mut out = Vec::new();
        let mut stack = vec![b];
        while let Some(t) = stack.pop() {
            if t < nvertex {
                out.push(t);
            } else {
                for &c in childs[t].iter().rev() {
                    stack.push(c);
                }
            }
        }
        out
    }

    #[allow(clippy::too_many_arguments)]
    fn assign_label(w: usize, t: u8, p: i64, st: &St, label: &mut Vec<u8>, labelend: &mut Vec<i64>,
                    inblossom: &Vec<usize>, bestedge: &mut Vec<i64>, queue: &mut Vec<usize>,
                    blossomchilds: &Vec<Vec<usize>>, blossombase: &Vec<i64>, mate: &Vec<i64>) {
        let b = inblossom[w];
        label[w] = t;
        label[b] = t;
        labelend[w] = p;
        labelend[b] = p;
        bestedge[w] = -1;
        bestedge[b] = -1;
        if t == 1 {
            queue.extend(blossom_leaves(b, st.nvertex, blossomchilds));
        } else if t == 2 {
            let base = blossombase[b] as usize;
            let m = mate[base];
            debug_assert!(m >= 0);
            let mb = st.endpoint[m as usize];
            assign_label(mb, 1, m ^ 1, st, label, labelend, inblossom, bestedge, queue, blossomchilds,
                         blossombase, mate);
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn scan_blossom(v0: usize, w0: usize, st: &St, label: &mut Vec<u8>, labelend: &Vec<i64>,
                    inblossom: &Vec<usize>, blossomparent: &Vec<i64>, blossombase: &Vec<i64>,
                    mate: &Vec<i64>) -> i64 {
        let mut path: Vec<usize> = Vec::new();
        let mut base: i64 = -1;
        let mut v: i64 = v0 as i64;
        let mut w: i64 = w0 as i64;
        while v != -1 || w != -1 {
            if v != -1 {
                let b = inblossom[v as usize];
                if label[b] & 4 != 0 {
                    base = blossombase[b];
                    break;
                }
                debug_assert!(label[b] == 1);
                path.push(b);
                label[b] = 5;
                if labelend[b] == -1 {
                    v = -1;
                } else {
                    let vv = st.endpoint[labelend[b] as usize];
                    let b2 = inblossom[vv];
                    debug_assert!(label[b2] == 2);
                    v = st.endpoint[labelend[b2] as usize] as i64;
                }
            }
            if w != -1 {
                std::mem::swap(&mut v, &mut w);
            }
        }
        for b in path {
            label[b] = 1;
        }
        let _ = (blossomparent, mate);
        base
    }

    #[allow(clippy::too_many_arguments)]
    fn add_blossom(base: usize, k: usize, st: &St, label: &mut Vec<u8>, labelend: &mut Vec<i64>,
                   inblossom: &mut Vec<usize>, blossomparent: &mut Vec<i64>, blossomchilds: &mut Vec<Vec<usize>>,
                   blossombase: &mut Vec<i64>, blossomendps: &mut Vec<Vec<usize>>, bestedge: &mut Vec<i64>,
                   blossombestedges: &mut Vec<Option<Vec<usize>>>, unusedblossoms: &mut Vec<usize>,
                   dualvar: &mut Vec<i64>, queue: &mut Vec<usize>, mate: &Vec<i64>) {
        let (v0, w0, _) = st.edges[k];
        let bb = inblossom[base];
        let mut bv = inblossom[v0];
        let mut bw = inblossom[w0];
        let b = unusedblossoms.pop().expect("blossom pool");
        blossombase[b] = base as i64;
        blossomparent[b] = -1;
        blossomparent[bb] = b as i64;
        let mut path: Vec<usize> = Vec::new();
        let mut endps: Vec<usize> = Vec::new();
        while bv != bb {
            blossomparent[bv] = b as i64;
            path.push(bv);
            endps.push(labelend[bv] as usize);
            debug_assert!(label[bv] == 2 || (label[bv] == 1 && labelend[bv] == mate[blossombase[bv] as usize]));
            let v = st.endpoint[labelend[bv] as usize];
            bv = inblossom[v];
        }
        path.push(bb);
        path.reverse();
        endps.reverse();
        endps.push(2 * k);
        while bw != bb {
            blossomparent[bw] = b as i64;
            path.push(bw);
            endps.push((labelend[bw] ^ 1) as usize);
            let w = st.endpoint[labelend[bw] as usize];
            bw = inblossom[w];
        }
        label[b] = 1;
        labelend[b] = labelend[bb];
        dualvar[b] = 0;
        blossomchilds[b] = path.clone();
        blossomendps[b] = endps;
        for v in blossom_leaves(b, st.nvertex, blossomchilds) {
            if label[inblossom[v]] == 2 {
                queue.push(v);
            }
            inblossom[v] = b;
        }
        // best edges to other S-blossoms
        let mut bestedgeto: Vec<i64> = vec![-1; 2 * st.nvertex];
        let slack = |k: usize, dualvar: &Vec<i64>| -> i64 {
            let (i, j, w) = st.edges[k];
            dualvar[i] + dualvar[j] - 2 * w
        };
        for &bvv in &path {
            let nblists: Vec<Vec<usize>> = match &blossombestedges[bvv] {
                None => blossom_leaves(bvv, st.nvertex, blossomchilds)
                    .into_iter()
                    .map(|v| st.neighbend[v].iter().map(|&p| p / 2).collect())
                    .collect(),
                Some(l) => vec![l.clone()],
            };
            for nblist in nblists {
                for k in nblist {
                    let (mut i, mut j, _) = st.edges[k];
                    if inblossom[j] == b {
                        std::mem::swap(&mut i, &mut j);
                    }
                    let bj = inblossom[j];
                    if bj != b && label[bj] == 1
                        && (bestedgeto[bj] == -1 || slack(k, dualvar) < slack(bestedgeto[bj] as usize, dualvar)) {
                        bestedgeto[bj] = k as i64;
                    }
                }
            }
            blossombestedges[bvv] = None;
            bestedge[bvv] = -1;
        }
        let best: Vec<usize> = bestedgeto.iter().filter(|&&k| k != -1).map(|&k| k as usize).collect();
        bestedge[b] = -1;
        for &k in &best {
            if bestedge[b] == -1 || slack(k, dualvar) < slack(bestedge[b] as usize, dualvar) {
                bestedge[b] = k as i64;
            }
        }
        blossombestedges[b] = Some(best);
    }

    #[allow(clippy::too_many_arguments)]
    fn expand_blossom(b: usize, endstage: bool, st: &St, label: &mut Vec<u8>, labelend: &mut Vec<i64>,
                      inblossom: &mut Vec<usize>, blossomparent: &mut Vec<i64>,
                      blossomchilds: &mut Vec<Vec<usize>>, blossombase: &mut Vec<i64>,
                      blossomendps: &mut Vec<Vec<usize>>, bestedge: &mut Vec<i64>,
                      blossombestedges: &mut Vec<Option<Vec<usize>>>, unusedblossoms: &mut Vec<usize>,
                      dualvar: &mut Vec<i64>, allowedge: &mut Vec<bool>, queue: &mut Vec<usize>,
                      mate: &Vec<i64>) {
        let childs = blossomchilds[b].clone();
        for &s in &childs {
            blossomparent[s] = -1;
            if s < st.nvertex {
                inblossom[s] = s;
            } else if endstage && dualvar[s] == 0 {
                expand_blossom(s, endstage, st, label, labelend, inblossom, blossomparent, blossomchilds,
                               blossombase, blossomendps, bestedge, blossombestedges, unusedblossoms, dualvar,
                               allowedge, queue, mate);
            } else {
                for v in blossom_leaves(s, st.nvertex, blossomchilds) {
                    inblossom[v] = s;
                }
            }
        }
        if !endstage && label[b] == 2 {
            let entrychild = inblossom[st.endpoint[(labelend[b] ^ 1) as usize]];
            let len = childs.len() as i64;
            let mut j = childs.iter().position(|&c| c == entrychild).unwrap() as i64;
            let (jstep, endptrick): (i64, usize) = if j & 1 != 0 {
                j -= len;
                (1, 0)
            } else {
                (-1, 1)
            };
            let endps = blossomendps[b].clone();
            let idx = |x: i64| -> usize { (((x % len) + len) % len) as usize };
            let mut p = labelend[b];
            while j != 0 {
                let ep_t = if jstep == 1 { idx(j) } else { idx(j - 1) };
                let ep = endps[ep_t];
                // relabel the T-sub-blossom
                label[st.endpoint[(p ^ 1) as usize]] = 0;
                let q = (ep ^ endptrick) as usize;
                label[st.endpoint[q ^ 1]] = 0;
                assign_label(st.endpoint[(p ^ 1) as usize], 2, p, st, label, labelend, inblossom, bestedge,
                             queue, blossomchilds, blossombase, mate);
                allowedge[q / 2] = true;
                j += jstep;
                let ep2_t = if jstep == 1 { idx(j) } else { idx(j - 1) };
                p = (endps[ep2_t] ^ endptrick) as i64;
                allowedge[(p / 2) as usize] = true;
                j += jstep;
            }
            let bv = childs[idx(j)];
            label[st.endpoint[(p ^ 1) as usize]] = 2;
            label[bv] = 2;
            labelend[st.endpoint[(p ^ 1) as usize]] = p;
            labelend[bv] = p;
            bestedge[bv] = -1;
            j += jstep;
            while childs[idx(j)] != entrychild {
                let bv = childs[idx(j)];
                if label[bv] == 1 {
                    j += jstep;
                    continue;
                }
                let mut found: i64 = -1;
                for v in blossom_leaves(bv, st.nvertex, blossomchilds) {
                    if label[v] != 0 {
                        found = v as i64;
                        break;
                    }
                }
                if found >= 0 {
                    let v = found as usize;
                    debug_assert!(label[v] == 2);
                    debug_assert!(inblossom[v] == bv);
                    label[v] = 0;
                    label[st.endpoint[mate[blossombase[bv] as usize] as usize]] = 0;
                    assign_label(v, 2, labelend[v], st, label, labelend, inblossom, bestedge, queue,
                                 blossomchilds, blossombase, mate);
                }
                j += jstep;
            }
        }
        label[b] = 0;
        labelend[b] = -1;
        blossomchilds[b] = Vec::new();
        blossomendps[b] = Vec::new();
        blossombase[b] = -1;
        blossombestedges[b] = None;
        bestedge[b] = -1;
        unusedblossoms.push(b);
    }

    #[allow(clippy::too_many_arguments)]
    fn augment_blossom(b: usize, v: usize, st: &St, mate: &mut Vec<i64>, blossomparent: &Vec<i64>,
                       blossomchilds: &mut Vec<Vec<usize>>, blossombase: &mut Vec<i64>,
                       blossomendps: &mut Vec<Vec<usize>>) {
        let mut t = v;
        while blossomparent[t] != b as i64 {
            t = blossomparent[t] as usize;
        }
        if t >= st.nvertex {
            augment_blossom(t, v, st, mate, blossomparent, blossomchilds, blossombase, blossomendps);
        }
        let childs = blossomchilds[b].clone();
        let endps = blossomendps[b].clone();
        let len = childs.len() as i64;
        let idx = |x: i64| -> usize { (((x % len) + len) % len) as usize };
        let i = childs.iter().position(|&c| c == t).unwrap() as i64;
        let mut j = i;
        let (jstep, endptrick): (i64, usize) = if i & 1 != 0 {
            j -= len;
            (1, 0)
        } else {
            (-1, 1)
        };
        while j != 0 {
            j += jstep;
            let t2 = childs[idx(j)];
            let p = endps[idx(j - endptrick as i64)] ^ endptrick;
            if t2 >= st.nvertex {
                augment_blossom(t2, st.endpoint[p], st, mate, blossomparent, blossomchilds, blossombase,
                                blossomendps);
            }
            j += jstep;
            let t3 = childs[idx(j)];
            if t3 >= st.nvertex {
                augment_blossom(t3, st.endpoint[p ^ 1], st, mate, blossomparent, blossomchilds, blossombase,
                                blossomendps);
            }
            mate[st.endpoint[p]] = (p ^ 1) as i64;
            mate[st.endpoint[p ^ 1]] = p as i64;
        }
        // rotate so the new base is first
        let iu = i as usize;
        let mut nc = childs[iu..].to_vec();
        nc.extend_from_slice(&childs[..iu]);
        let mut ne = endps[iu..].to_vec();
        ne.extend_from_slice(&endps[..iu]);
        blossomchilds[b] = nc;
        blossomendps[b] = ne;
        blossombase[b] = blossombase[blossomchilds[b][0]];
        debug_assert!(blossombase[b] == v as i64);
    }

    #[allow(clippy::too_many_arguments)]
    fn augment_matching(k: usize, st: &St, mate: &mut Vec<i64>, labelend: &Vec<i64>, inblossom: &Vec<usize>,
                        blossomparent: &Vec<i64>, blossomchilds: &mut Vec<Vec<usize>>,
                        blossombase: &mut Vec<i64>, blossomendps: &mut Vec<Vec<usize>>, label: &Vec<u8>) {
        let (v0, w0, _) = st.edges[k];
        for &(s0, p0) in &[(v0, 2 * k + 1), (w0, 2 * k)] {
            let mut s = s0;
            let mut p = p0;
            loop {
                let bs = inblossom[s];
                debug_assert!(label[bs] == 1);
                if bs >= st.nvertex {
                    augment_blossom(bs, s, st, mate, blossomparent, blossomchilds, blossombase, blossomendps);
                }
                mate[s] = p as i64;
                if labelend[bs] == -1 {
                    break;
                }
                let t = st.endpoint[labelend[bs] as usize];
                let bt = inblossom[t];
                debug_assert!(label[bt] == 2);
                s = st.endpoint[labelend[bt] as usize];
                let j = st.endpoint[(labelend[bt] ^ 1) as usize];
                debug_assert!(blossombase[bt] == t as i64);
                if bt >= st.nvertex {
                    augment_blossom(bt, j, st, mate, blossomparent, blossomchilds, blossombase, blossomendps);
                }
                mate[j] = labelend[bt];
                p = (labelend[bt] ^ 1) as usize;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn total(m: &[i64], e: &[(usize, usize, i64)]) -> i64 {
        e.iter().filter(|&&(i, j, _)| m[i] == j as i64).map(|e| e.2).sum()
    }

    fn brute(n: usize, e: &[(usize, usize, i64)]) -> i64 {
        fn rec(k: usize, used: &mut Vec<bool>, e: &[(usize, usize, i64)]) -> i64 {
            if k == e.len() {
                return 0;
            }
            let mut best = rec(k + 1, used, e);
            let (i, j, w) = e[k];
            if !used[i] && !used[j] {
                used[i] = true;
                used[j] = true;
                best = best.max(w + rec(k + 1, used, e));
                used[i] = false;
                used[j] = false;
            }
            best
        }
        rec(0, &mut vec![false; n], e)
    }

    #[test]
    fn small_graphs() {
        assert_eq!(max_weight_matching(2, &[(0, 1, 1)]), vec![1, 0]);
        let e = [(1, 2, 10), (2, 3, 11)];
        assert_eq!(max_weight_matching(4, &e), vec![-1, -1, 3, 2]);
    }

    #[test]
    fn random_graphs_match_brute_force() {
        let mut seed: u64 = 12345;
        let mut rnd = |m: u64| -> u64 {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            (seed >> 33) % m
        };
        for _case in 0..3000 {
            let n = 2 + rnd(9) as usize;
            let mut e = Vec::new();
            for i in 0..n {
                for j in i + 1..n {
                    if rnd(100) < 45 {
                        e.push((i, j, 1 + rnd(20) as i64));
                    }
                }
            }
            if e.len() > 18 {
                e.truncate(18);
            }
            let m = max_weight_matching(n, &e);
            for v in 0..n {
                if m[v] >= 0 {
                    assert_eq!(m[m[v] as usize], v as i64, "not symmetric");
                }
            }
            assert_eq!(total(&m, &e), brute(n, &e), "graph {:?}", e);
        }
    }
}
